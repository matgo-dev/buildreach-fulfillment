"""商品图片 reconcile + 序列化(product_images 表)。

写接口按 image_key 声明期望图集,本服务对账行到期望态(create/edit 统一,免 diff 协议)。
封面切换的写序(评审 S5):PG 部分唯一索引逐行校验、不可延迟,故换封面必须
**先降旧 MAIN→GALLERY,再升新 MAIN**,否则事务中途两行 MAIN 立即撞唯一索引。
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.product_image import ImageType, ProductImage
from app.services.storage import get_attachment_storage

logger = logging.getLogger(__name__)


def to_image_out(row: ProductImage) -> dict:
    return {"id": row.id, "image_key": row.image_key, "image_type": row.image_type,
            "sort_order": row.sort_order, "sku_id": row.sku_id}


async def list_spu_images(db: AsyncSession, spu_id: int) -> list[dict]:
    """SPU 级图(sku_id IS NULL),封面 MAIN 在前,再按 sort_order。"""
    rows = (await db.execute(
        select(ProductImage).where(
            ProductImage.spu_id == spu_id, ProductImage.sku_id.is_(None))
        .order_by(ProductImage.sort_order, ProductImage.id))).scalars().all()
    return [to_image_out(r) for r in rows]


async def list_sku_images(db: AsyncSession, sku_id: int) -> list[dict]:
    rows = (await db.execute(
        select(ProductImage).where(ProductImage.sku_id == sku_id)
        .order_by(ProductImage.sort_order, ProductImage.id))).scalars().all()
    return [to_image_out(r) for r in rows]


async def sku_images_by_sku(db: AsyncSession, sku_ids: list[int]) -> dict[int, list[dict]]:
    """批量取多个 SKU 的图(单查 WHERE sku_id IN,免 get_spu 逐 SKU N+1)。"""
    if not sku_ids:
        return {}
    rows = (await db.execute(
        select(ProductImage).where(ProductImage.sku_id.in_(sku_ids))
        .order_by(ProductImage.sku_id, ProductImage.sort_order, ProductImage.id))).scalars().all()
    out: dict[int, list[dict]] = {sid: [] for sid in sku_ids}
    for r in rows:
        out.setdefault(r.sku_id, []).append(to_image_out(r))
    return out


async def cover_keys(db: AsyncSession, spu_ids: list[int]) -> dict[int, str]:
    """批量取每个 SPU 的封面 key:MAIN 优先,否则 GALLERY 最小 sort_order(避免 N+1)。"""
    if not spu_ids:
        return {}
    rows = (await db.execute(
        select(ProductImage.spu_id, ProductImage.image_key, ProductImage.image_type,
               ProductImage.sort_order)
        .where(ProductImage.spu_id.in_(spu_ids), ProductImage.sku_id.is_(None),
               ProductImage.image_type.in_((ImageType.MAIN, ImageType.GALLERY))))).all()
    best: dict[int, tuple[int, int, str]] = {}
    for spu_id, key, itype, sort in rows:
        rank = 0 if itype == ImageType.MAIN else 1
        cur = best.get(spu_id)
        if cur is None or (rank, sort) < (cur[0], cur[1]):
            best[spu_id] = (rank, sort, key)
    return {sid: v[2] for sid, v in best.items()}


async def reconcile_spu_images(db: AsyncSession, spu_id: int, refs: list[dict]) -> list[str]:
    """对账 SPU 级图(sku_id IS NULL)到 refs(已由 schema 校验:恰 1 MAIN / caps / key 唯一)。

    写序保证不撞部分唯一 MAIN 索引:删缺失 → 降级(target≠MAIN 的既有行)→ 插新 → 升 MAIN。
    返回本次被删除的 image_key(供提交后 GC 孤儿存储对象,见 gc_orphan_objects)。
    """
    existing = {r.image_key: r for r in (await db.execute(
        select(ProductImage).where(
            ProductImage.spu_id == spu_id, ProductImage.sku_id.is_(None)))).scalars().all()}
    desired = {ref["image_key"]: ref for ref in refs}

    # 1. 删除不在期望内的行
    removed = [key for key in existing if key not in desired]
    for key in removed:
        await db.delete(existing[key])
    await db.flush()

    # 2. 既有行 target≠MAIN:改类型/排序(此步降掉旧 MAIN)
    for key, ref in desired.items():
        if key in existing and ref["image_type"] != ImageType.MAIN:
            existing[key].image_type = ref["image_type"]
            existing[key].sort_order = ref["sort_order"]
    await db.flush()

    # 3. 插入新 key(新 MAIN 安全:旧 MAIN 已在步 2 降级)
    for key, ref in desired.items():
        if key not in existing:
            db.add(ProductImage(spu_id=spu_id, sku_id=None, image_key=key,
                                image_type=ref["image_type"], sort_order=ref["sort_order"]))
    await db.flush()

    # 4. 既有 key 升 MAIN
    for key, ref in desired.items():
        if key in existing and ref["image_type"] == ImageType.MAIN:
            existing[key].image_type = ImageType.MAIN
            existing[key].sort_order = ref["sort_order"]
    await db.flush()
    return removed


async def reconcile_sku_images(
    db: AsyncSession, spu_id: int, sku_id: int, refs: list[dict]) -> list[str]:
    """对账 SKU 级图(sku_id=本 SKU)到 refs;SKU 图一律 GALLERY(无 MAIN/DETAIL 语义)。

    返回被删除的 image_key(供提交后 GC,见 gc_orphan_objects)。
    """
    existing = {r.image_key: r for r in (await db.execute(
        select(ProductImage).where(ProductImage.sku_id == sku_id))).scalars().all()}
    desired = {ref["image_key"]: ref for ref in refs}

    removed = [key for key in existing if key not in desired]
    for key in removed:
        await db.delete(existing[key])
    await db.flush()

    for key, ref in desired.items():
        if key in existing:
            existing[key].sort_order = ref["sort_order"]
        else:
            db.add(ProductImage(spu_id=spu_id, sku_id=sku_id, image_key=key,
                                image_type=ImageType.GALLERY, sort_order=ref["sort_order"]))
    await db.flush()
    return removed


async def gc_orphan_objects(db: AsyncSession, keys: list[str]) -> None:
    """提交后回收孤儿存储对象:仅当某 image_key 已无任何 product_images 行引用时才删存储对象。

    **必须在事务提交后调用** —— reconcile 在事务内删行,若此时删存储对象而事务回滚,
    会删掉仍被引用的活文件。且同一 key 可能被 SPU 行与 SKU 行同时引用(两条部分唯一
    索引各自放行),故删前按 IN 查残余引用,只删真正无引用的。存储删除是尽力而为,
    失败仅告警(孤儿文件残留不影响正确性)。
    """
    if not keys:
        return
    still = set((await db.execute(
        select(ProductImage.image_key).where(
            ProductImage.image_key.in_(keys)))).scalars().all())
    storage = get_attachment_storage()
    for key in set(keys) - still:
        try:
            storage.delete(key)
        except Exception:
            logger.warning("GC 删除存储对象失败(忽略,孤儿残留): %s", key)
