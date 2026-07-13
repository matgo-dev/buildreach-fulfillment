import pytest
from app.services import spu_service
from app.core.exceptions import ConflictError, NotFoundError
from app.db.models.spu import SpuStatus


async def _seed_leaf_category(db):
    """确保有一个叶子分类可挂;返回其 code。参考 test_category_model_integration.py。"""
    from app.db.models.category import Category
    cat = Category(code="99.001", parent_code=None, name_i18n={"zh": "测试叶"},
                   level=1, is_leaf=True, is_active=True, sort_order=0)
    db.add(cat)
    await db.flush()
    return cat.code


@pytest.mark.asyncio
async def test_create_spu_allocates_code(db_session):
    code = await _seed_leaf_category(db_session)
    spu = await spu_service.create_spu(
        db_session, category_code=code, name_i18n={"zh": "钢管"}, image_refs=[{"image_key": "img/test.jpg", "image_type": "MAIN", "sort_order": 0}],
        actor_user_id=1, actor_user_email="a@b.c")
    assert spu.spu_code.startswith("SPU")
    assert len(spu.spu_code) == 11


@pytest.mark.asyncio
async def test_create_spu_rejects_non_leaf_category(db_session):
    from app.db.models.category import Category
    parent = Category(code="88", parent_code=None, name_i18n={"zh": "父"},
                      level=1, is_leaf=False, is_active=True, sort_order=0)
    db_session.add(parent)
    await db_session.flush()
    with pytest.raises((ConflictError, NotFoundError, ValueError)):
        await spu_service.create_spu(db_session, category_code="88",
            name_i18n={"zh": "x"}, image_refs=[{"image_key": "img/test.jpg", "image_type": "MAIN", "sort_order": 0}],
            actor_user_id=1, actor_user_email="a@b.c")


@pytest.mark.asyncio
async def test_soft_delete_spu_blocked_by_active_skus(db_session):
    code = await _seed_leaf_category(db_session)
    spu = await spu_service.create_spu(db_session, category_code=code,
        name_i18n={"zh": "x"}, image_refs=[{"image_key": "img/test.jpg", "image_type": "MAIN", "sort_order": 0}],
        actor_user_id=1, actor_user_email="a@b.c")
    from app.services import sku_service
    await sku_service.create_sku(db_session, spu_id=spu.id, unit="piece",
        reference_price=None, name_i18n={"zh": "sku"}, spec_items=[],
        actor_user_id=1, actor_user_email="a@b.c")
    with pytest.raises(ConflictError):
        await spu_service.soft_delete_spu(db_session, spu_id=spu.id,
            actor_user_id=1, actor_user_email="a@b.c")


@pytest.mark.asyncio
async def test_get_spu_filters_deleted(db_session):
    code = await _seed_leaf_category(db_session)
    spu = await spu_service.create_spu(db_session, category_code=code,
        name_i18n={"zh": "x"}, image_refs=[{"image_key": "img/test.jpg", "image_type": "MAIN", "sort_order": 0}],
        actor_user_id=1, actor_user_email="a@b.c")
    await spu_service.soft_delete_spu(db_session, spu_id=spu.id,
        actor_user_id=1, actor_user_email="a@b.c")
    with pytest.raises(NotFoundError):
        await spu_service.get_spu(db_session, spu.id)


@pytest.mark.asyncio
async def test_update_spu_rejects_non_leaf_category(db_session):
    from app.db.models.category import Category
    code = await _seed_leaf_category(db_session)
    spu = await spu_service.create_spu(db_session, category_code=code,
        name_i18n={"zh": "x"}, image_refs=[{"image_key": "img/test.jpg", "image_type": "MAIN", "sort_order": 0}],
        actor_user_id=1, actor_user_email="a@b.c")
    parent = Category(code="77", parent_code=None, name_i18n={"zh": "父"},
                      level=1, is_leaf=False, is_active=True, sort_order=0)
    db_session.add(parent)
    await db_session.flush()
    with pytest.raises(ConflictError):
        await spu_service.update_spu(db_session, spu_id=spu.id, category_code="77",
            actor_user_id=1, actor_user_email="a@b.c")


@pytest.mark.asyncio
async def test_update_spu_updates_name(db_session):
    code = await _seed_leaf_category(db_session)
    spu = await spu_service.create_spu(db_session, category_code=code,
        name_i18n={"zh": "旧名"}, image_refs=[{"image_key": "img/test.jpg", "image_type": "MAIN", "sort_order": 0}],
        actor_user_id=1, actor_user_email="a@b.c")
    updated = await spu_service.update_spu(db_session, spu_id=spu.id,
        name_i18n={"zh": "新名"}, actor_user_id=1, actor_user_email="a@b.c")
    assert updated.name_i18n["zh"] == "新名"


@pytest.mark.asyncio
async def test_set_spu_status(db_session):
    code = await _seed_leaf_category(db_session)
    from decimal import Decimal
    from app.services import sku_service
    from app.core.exceptions import ProductIncompleteError
    spu = await spu_service.create_spu(db_session, category_code=code,
        name_i18n={"zh": "x"}, image_refs=[{"image_key": "img/test.jpg", "image_type": "MAIN", "sort_order": 0}],
        actor_user_id=1, actor_user_email="a@b.c")
    assert spu.status == SpuStatus.DRAFT  # 新建默认草稿
    # 无带价在售 SKU → 启用被拒(完备性)
    with pytest.raises(ProductIncompleteError):
        await spu_service.set_spu_status(db_session, spu_id=spu.id,
            status=SpuStatus.ACTIVE, actor_user_id=1, actor_user_email="a@b.c")
    # 建带价在售 SKU 后可启用,再停用
    await sku_service.create_sku(db_session, spu_id=spu.id, unit="piece",
        reference_price=Decimal("1.00"), name_i18n={"zh": "a"}, spec_items=[],
        actor_user_id=1, actor_user_email="a@b.c")
    activated = await spu_service.set_spu_status(db_session, spu_id=spu.id,
        status=SpuStatus.ACTIVE, actor_user_id=1, actor_user_email="a@b.c")
    assert activated.status == SpuStatus.ACTIVE
    updated = await spu_service.set_spu_status(db_session, spu_id=spu.id,
        status=SpuStatus.INACTIVE, actor_user_id=1, actor_user_email="a@b.c")
    assert updated.status == SpuStatus.INACTIVE


@pytest.mark.asyncio
async def test_soft_delete_spu_succeeds_without_active_skus(db_session):
    code = await _seed_leaf_category(db_session)
    spu = await spu_service.create_spu(db_session, category_code=code,
        name_i18n={"zh": "x"}, image_refs=[{"image_key": "img/test.jpg", "image_type": "MAIN", "sort_order": 0}],
        actor_user_id=1, actor_user_email="a@b.c")
    await spu_service.soft_delete_spu(db_session, spu_id=spu.id,
        actor_user_id=1, actor_user_email="a@b.c")
    with pytest.raises(NotFoundError):
        await spu_service.get_spu(db_session, spu.id)


@pytest.mark.asyncio
async def test_list_spus_filters_and_paginates(db_session):
    code = await _seed_leaf_category(db_session)
    for i in range(3):
        await spu_service.create_spu(db_session, category_code=code,
            name_i18n={"zh": f"钢管{i}"}, image_refs=[{"image_key": "img/test.jpg", "image_type": "MAIN", "sort_order": 0}],
            actor_user_id=1, actor_user_email="a@b.c")
    rows, total = await spu_service.list_spus(db_session, category_code=code, page=1, size=2)
    assert total == 3
    assert len(rows) == 2

    rows2, total2 = await spu_service.list_spus(db_session, keyword="钢管1")
    assert total2 == 1
    assert rows2[0].name_i18n["zh"] == "钢管1"

    rows3, total3 = await spu_service.list_spus(db_session, keyword=rows[0].spu_code)
    assert total3 == 1
