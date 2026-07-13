"""商品生命周期状态机 + 编辑/删除门禁(设计:CLAUDE.md 设计决策方法论,三态 DRAFT/ACTIVE/INACTIVE)。

语义 = 能否被下游(报价)选用,非对外可见。覆盖:新建默认 DRAFT;启用完备性(须带价在售 SKU);
ACTIVE 锁编辑/删除(先停用再改);SKU 写受父 SPU EDITABLE 约束;SKU 上下架豁免;
停用最后一个带价在售 SKU 联动把 SPU 下架;非法转移拒绝。
"""
import pytest
from sqlalchemy import select

from app.db.models.category import Category

MAIN_IMG = [{"image_key": "img/m.jpg", "image_type": "MAIN", "sort_order": 0}]


async def _seed_category(db_session, code="10"):
    if not (await db_session.execute(
            select(Category).where(Category.code == code))).scalar_one_or_none():
        db_session.add(Category(code=code, parent_code=None, name_i18n={"zh": "阀门"},
                                level=1, is_leaf=True, sort_order=0))
        await db_session.commit()


async def _draft_spu(client, h) -> int:
    r = await client.post("/api/v1/spus", headers=h, json={
        "category_code": "10", "name_i18n": {"zh": "钢管"}, "images": MAIN_IMG})
    assert r.status_code in (200, 201), r.text
    return r.json()["data"]["id"]


async def _add_sku(client, h, sid, *, price="12.50", name="钢管A") -> int:
    body = {"spu_id": sid, "unit": "piece", "name_i18n": {"zh": name}, "spec_items": []}
    if price is not None:
        body["reference_price"] = price
    r = await client.post("/api/v1/skus", headers=h, json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()["data"]["id"]


async def _set_status(client, h, sid, status):
    return await client.patch(f"/api/v1/spus/{sid}/status", headers=h, json={"status": status})


async def _get_spu(client, h, sid):
    return (await client.get(f"/api/v1/spus/{sid}", headers=h)).json()["data"]


# ── 新建默认 DRAFT ──

@pytest.mark.asyncio
async def test_create_spu_defaults_to_draft(client, product_operator_headers, db_session):
    await _seed_category(db_session)
    sid = await _draft_spu(client, product_operator_headers)
    assert (await _get_spu(client, product_operator_headers, sid))["status"] == "DRAFT"


@pytest.mark.asyncio
async def test_draft_spu_is_editable(client, product_operator_headers, db_session):
    await _seed_category(db_session)
    sid = await _draft_spu(client, product_operator_headers)
    r = await client.put(f"/api/v1/spus/{sid}", headers=product_operator_headers,
                         json={"name_i18n": {"zh": "改名"}})
    assert r.status_code == 200, r.text


# ── 启用完备性:须带价在售 SKU ──

@pytest.mark.asyncio
async def test_activate_without_any_sku_rejected(client, product_operator_headers, db_session):
    await _seed_category(db_session)
    sid = await _draft_spu(client, product_operator_headers)
    r = await _set_status(client, product_operator_headers, sid, "ACTIVE")
    assert r.status_code == 409, r.text  # ProductIncomplete


@pytest.mark.asyncio
async def test_activate_with_priceless_sku_ok(client, product_operator_headers, db_session):
    """启用完备性只看"有在售 SKU",不卡参考价 —— 报价成交价销售自填,不依赖内部采购参考价。"""
    await _seed_category(db_session)
    sid = await _draft_spu(client, product_operator_headers)
    await _add_sku(client, product_operator_headers, sid, price=None)  # 无价但在售
    r = await _set_status(client, product_operator_headers, sid, "ACTIVE")
    assert r.status_code == 200, r.text
    assert (await _get_spu(client, product_operator_headers, sid))["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_activate_with_priced_sku_ok(client, product_operator_headers, db_session):
    await _seed_category(db_session)
    sid = await _draft_spu(client, product_operator_headers)
    await _add_sku(client, product_operator_headers, sid)
    r = await _set_status(client, product_operator_headers, sid, "ACTIVE")
    assert r.status_code == 200, r.text
    assert (await _get_spu(client, product_operator_headers, sid))["status"] == "ACTIVE"


# ── ACTIVE 锁编辑 / 删除 / SKU 写 ──

@pytest.mark.asyncio
async def test_active_spu_edit_and_delete_blocked(client, product_operator_headers, db_session):
    await _seed_category(db_session)
    h = product_operator_headers
    sid = await _draft_spu(client, h)
    await _add_sku(client, h, sid)
    await _set_status(client, h, sid, "ACTIVE")
    assert (await client.put(f"/api/v1/spus/{sid}", headers=h,
            json={"name_i18n": {"zh": "改名"}})).status_code == 409
    assert (await client.delete(f"/api/v1/spus/{sid}", headers=h)).status_code == 409


@pytest.mark.asyncio
async def test_active_spu_sku_writes_blocked(client, product_operator_headers, db_session):
    await _seed_category(db_session)
    h = product_operator_headers
    sid = await _draft_spu(client, h)
    skid = await _add_sku(client, h, sid)
    await _set_status(client, h, sid, "ACTIVE")
    # 父 SPU 启用中 → 建/改/删 SKU 均拒
    assert (await client.post("/api/v1/skus", headers=h, json={
        "spu_id": sid, "unit": "piece", "name_i18n": {"zh": "B"}, "spec_items": []})).status_code == 409
    assert (await client.put(f"/api/v1/skus/{skid}", headers=h,
            json={"name_i18n": {"zh": "改"}})).status_code == 409
    assert (await client.delete(f"/api/v1/skus/{skid}", headers=h)).status_code == 409


# ── SKU 上下架豁免 SPU 锁 ──

@pytest.mark.asyncio
async def test_sku_status_toggle_exempt_under_active_spu(client, product_operator_headers, db_session):
    await _seed_category(db_session)
    h = product_operator_headers
    sid = await _draft_spu(client, h)
    s1 = await _add_sku(client, h, sid, name="A")
    await _add_sku(client, h, sid, name="B")  # 第二个带价在售,停 s1 后 SPU 仍完备
    await _set_status(client, h, sid, "ACTIVE")
    r = await client.patch(f"/api/v1/skus/{s1}/status", headers=h, json={"status": "INACTIVE"})
    assert r.status_code == 200, r.text  # 启用中仍可停售单个变体
    assert (await _get_spu(client, h, sid))["status"] == "ACTIVE"  # 还有 B,SPU 不联动


# ── 停用最后一个带价在售 SKU → SPU 联动下架 ──

@pytest.mark.asyncio
async def test_deactivating_last_priced_sku_cascades_spu_inactive(
        client, product_operator_headers, db_session):
    await _seed_category(db_session)
    h = product_operator_headers
    sid = await _draft_spu(client, h)
    s1 = await _add_sku(client, h, sid)
    await _set_status(client, h, sid, "ACTIVE")
    r = await client.patch(f"/api/v1/skus/{s1}/status", headers=h, json={"status": "INACTIVE"})
    assert r.status_code == 200, r.text
    assert (await _get_spu(client, h, sid))["status"] == "INACTIVE"  # 无带价在售 SKU 联动下架


# ── 停用后可编辑/可删 ──

@pytest.mark.asyncio
async def test_deactivate_then_editable_and_deletable(client, product_operator_headers, db_session):
    await _seed_category(db_session)
    h = product_operator_headers
    sid = await _draft_spu(client, h)
    skid = await _add_sku(client, h, sid)
    await _set_status(client, h, sid, "ACTIVE")
    assert (await _set_status(client, h, sid, "INACTIVE")).status_code == 200
    assert (await client.put(f"/api/v1/spus/{sid}", headers=h,
            json={"name_i18n": {"zh": "停用后改名"}})).status_code == 200
    assert (await client.delete(f"/api/v1/skus/{skid}", headers=h)).status_code == 200
    assert (await client.delete(f"/api/v1/spus/{sid}", headers=h)).status_code == 200


# ── 非法转移 ──

@pytest.mark.asyncio
async def test_illegal_transition_draft_to_inactive(client, product_operator_headers, db_session):
    await _seed_category(db_session)
    sid = await _draft_spu(client, product_operator_headers)
    r = await _set_status(client, product_operator_headers, sid, "INACTIVE")
    assert r.status_code == 409, r.text  # DRAFT→INACTIVE 不在白名单


@pytest.mark.asyncio
async def test_illegal_transition_active_to_active(client, product_operator_headers, db_session):
    await _seed_category(db_session)
    h = product_operator_headers
    sid = await _draft_spu(client, h)
    await _add_sku(client, h, sid)
    await _set_status(client, h, sid, "ACTIVE")
    assert (await _set_status(client, h, sid, "ACTIVE")).status_code == 409  # ACTIVE→ACTIVE 非法
