"""发运增量:装柜/离港状态机 + 装柜守卫(42003/42004)+ 出库撤销守卫(41910)
+ 分状态字段门禁(42005,diff 语义)+ 乐观锁(42006)+ 发运全程库存不变回归。

发运不碰库存/应收:所有船务动作对 compute_stock_balance 派生结果零影响(回归断言)。
"""
import datetime as _dt

import pytest

from tests.inventory_helpers import find_line
from tests.outbound_helpers import (
    create_outbound,
    create_shipment,
    make_loadable_shipment,
    setup_available_stock,
)

pytestmark = pytest.mark.asyncio


async def _available(client, headers, so_id, sku_id) -> float:
    """经 /outboundable-lines(compute_stock_balance 单一源头)取某 SO 某 sku 可发量。"""
    r = await client.get(f"/api/v1/sales-orders/{so_id}/outboundable-lines", headers=headers)
    assert r.status_code == 200, r.text
    return find_line(r.json()["data"]["items"], sku_id)["available_qty"]


# ---------- 状态机:合法全程 ----------


async def test_full_lifecycle_load_depart_undepart_unload(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """OPEN→LOADED→DEPARTED→(撤离港)LOADED→(撤装柜)OPEN,loaded_at/atd 随动。"""
    d = await make_loadable_shipment(client, db_session, sales_headers, purchaser_headers,
                                     logistics_headers)
    sid = d["shipment"]["id"]

    ld = await client.post(f"/api/v1/shipments/{sid}/load", headers=logistics_headers, json={})
    assert ld.status_code == 200, ld.text
    body = ld.json()["data"]["shipment"]
    assert body["status"] == "LOADED" and body["loaded_at"] is not None

    dp = await client.post(f"/api/v1/shipments/{sid}/depart", headers=logistics_headers, json={})
    assert dp.status_code == 200
    assert dp.json()["data"]["shipment"]["status"] == "DEPARTED"
    assert dp.json()["data"]["shipment"]["atd"] is not None

    ud = await client.post(f"/api/v1/shipments/{sid}/undepart", headers=logistics_headers)
    assert ud.status_code == 200
    assert ud.json()["data"]["shipment"]["status"] == "LOADED"
    assert ud.json()["data"]["shipment"]["atd"] is None   # 撤离港清 atd

    un = await client.post(f"/api/v1/shipments/{sid}/unload", headers=logistics_headers)
    assert un.status_code == 200
    assert un.json()["data"]["shipment"]["status"] == "OPEN"
    assert un.json()["data"]["shipment"]["loaded_at"] is None   # 撤装柜清 loaded_at


async def test_illegal_transitions_42002(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """非法转移一律 42002(单义):OPEN 不能 depart/undepart/unload;LOADED 不能再 load/cancel;
    DEPARTED 不能 depart/unload。"""
    d = await make_loadable_shipment(client, db_session, sales_headers, purchaser_headers,
                                     logistics_headers)
    sid = d["shipment"]["id"]

    for path in ("depart", "undepart", "unload"):
        r = await client.post(f"/api/v1/shipments/{sid}/{path}", headers=logistics_headers,
                              json={})
        assert r.status_code == 409 and r.json()["code"] == 42002, (path, r.text)

    await client.post(f"/api/v1/shipments/{sid}/load", headers=logistics_headers, json={})
    # LOADED 不能再装柜,也不能直接取消(cancel 仅 OPEN 可达)。
    again = await client.post(f"/api/v1/shipments/{sid}/load", headers=logistics_headers, json={})
    assert again.status_code == 409 and again.json()["code"] == 42002
    canc = await client.post(f"/api/v1/shipments/{sid}/cancel", headers=logistics_headers)
    assert canc.status_code == 409 and canc.json()["code"] == 42002

    await client.post(f"/api/v1/shipments/{sid}/depart", headers=logistics_headers, json={})
    for path in ("depart", "unload"):
        r = await client.post(f"/api/v1/shipments/{sid}/{path}", headers=logistics_headers,
                              json={})
        assert r.status_code == 409 and r.json()["code"] == 42002, (path, r.text)


# ---------- 装柜守卫 ----------


async def test_load_empty_shipment_42004(client, logistics_headers):
    """空柜(无出库单)装柜 → 42004。"""
    ship = await create_shipment(client, logistics_headers)
    r = await client.post(f"/api/v1/shipments/{ship['id']}/load", headers=logistics_headers,
                          json={})
    assert r.status_code == 409 and r.json()["code"] == 42004


async def test_load_with_draft_outbound_42003(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """柜内存在草稿出库单 → 42003,biz_data 带草稿单号列表。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers,
                                      so_qty=10, received=10)
    so_id, so_lines = ctx["sales_order_id"], ctx["so_lines"]
    ship = await create_shipment(client, logistics_headers)
    cr = await create_outbound(client, logistics_headers, sales_order_id=so_id,
                               shipment_id=ship["id"],
                               lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 3}])
    ob_no = cr.json()["data"]["order"]["no"]
    r = await client.post(f"/api/v1/shipments/{ship['id']}/load", headers=logistics_headers,
                          json={})
    assert r.status_code == 409 and r.json()["code"] == 42003
    assert ob_no in r.json()["data"]["draft_nos"]


async def test_load_records_seal_and_container(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """装柜动作可补录封条/柜号(封条贴上才知)。"""
    d = await make_loadable_shipment(client, db_session, sales_headers, purchaser_headers,
                                     logistics_headers)
    sid = d["shipment"]["id"]
    r = await client.post(f"/api/v1/shipments/{sid}/load", headers=logistics_headers,
                          json={"seal_no": "SEALX", "container_no": "TCLU9999999"})
    assert r.status_code == 200, r.text
    b = r.json()["data"]["shipment"]
    assert b["seal_no"] == "SEALX" and b["container_no"] == "TCLU9999999"


# ---------- 出库撤销守卫 41910 + 解冻路径 ----------


async def test_revert_outbound_blocked_after_load_41910(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """柜装柜后柜内出库单不可撤(41910);撤装柜(LOADED→OPEN)后解冻,撤销成功。"""
    d = await make_loadable_shipment(client, db_session, sales_headers, purchaser_headers,
                                     logistics_headers)
    sid, ob_id = d["shipment"]["id"], d["outbound_id"]
    await client.post(f"/api/v1/shipments/{sid}/load", headers=logistics_headers, json={})
    blocked = await client.post(f"/api/v1/outbound-orders/{ob_id}/revert",
                                headers=logistics_headers, json={})
    assert blocked.status_code == 409 and blocked.json()["code"] == 41910
    # 撤装柜后解冻。
    await client.post(f"/api/v1/shipments/{sid}/unload", headers=logistics_headers)
    ok = await client.post(f"/api/v1/outbound-orders/{ob_id}/revert",
                           headers=logistics_headers, json={})
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["order"]["status"] == "DRAFT"


async def test_revert_outbound_blocked_after_depart_41910(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """柜已发运(DEPARTED,非 OPEN)柜内出库单同样不可撤 → 41910。"""
    d = await make_loadable_shipment(client, db_session, sales_headers, purchaser_headers,
                                     logistics_headers)
    sid, ob_id = d["shipment"]["id"], d["outbound_id"]
    await client.post(f"/api/v1/shipments/{sid}/load", headers=logistics_headers, json={})
    await client.post(f"/api/v1/shipments/{sid}/depart", headers=logistics_headers, json={})
    blocked = await client.post(f"/api/v1/outbound-orders/{ob_id}/revert",
                                headers=logistics_headers, json={})
    assert blocked.status_code == 409 and blocked.json()["code"] == 41910


# ---------- 字段门禁 42005(diff 语义)+ 乐观锁 42006 ----------


async def test_field_gate_open_allows_all(client, logistics_headers):
    """OPEN:柜物理组 + 船务组全可改。"""
    ship = await create_shipment(client, logistics_headers)
    r = await client.patch(f"/api/v1/shipments/{ship['id']}", headers=logistics_headers, json={
        "container_no": "AAAU1111111", "container_type": "40HQ", "seal_no": "S1",
        "vessel_name": "EVER GIVEN", "voyage_no": "V001", "booking_no": "BK1",
        "bl_no": "BL1", "port_of_loading": "Shanghai", "port_of_discharge": "Mombasa",
        "etd": "2026-08-01", "eta": "2026-09-01",
        "expected_updated_at": ship["updated_at"]})
    assert r.status_code == 200, r.text
    b = r.json()["data"]["shipment"]
    assert b["vessel_name"] == "EVER GIVEN" and b["etd"] == "2026-08-01"


async def test_field_gate_loaded_locks_container_42005(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """LOADED:改柜物理组(container_no)→ 42005 带字段名;改船务组(船名)放行。"""
    d = await make_loadable_shipment(client, db_session, sales_headers, purchaser_headers,
                                     logistics_headers)
    sid = d["shipment"]["id"]
    load = await client.post(f"/api/v1/shipments/{sid}/load", headers=logistics_headers, json={})
    upd = load.json()["data"]["shipment"]["updated_at"]
    # 改柜物理组被拒。
    bad = await client.patch(f"/api/v1/shipments/{sid}", headers=logistics_headers, json={
        "container_no": "CHANGED0001", "expected_updated_at": upd})
    assert bad.status_code == 400 and bad.json()["code"] == 42005
    assert "container_no" in bad.json()["data"]["fields"]
    # 改船务组放行。
    ok = await client.patch(f"/api/v1/shipments/{sid}", headers=logistics_headers, json={
        "vessel_name": "MSC", "expected_updated_at": upd})
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["shipment"]["vessel_name"] == "MSC"


async def test_field_gate_departed_only_bl_eta_note(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """DEPARTED:bl_no/eta/note 可补;船务组其余(vessel_name)→ 42005。"""
    d = await make_loadable_shipment(client, db_session, sales_headers, purchaser_headers,
                                     logistics_headers)
    sid = d["shipment"]["id"]
    await client.post(f"/api/v1/shipments/{sid}/load", headers=logistics_headers, json={})
    dep = await client.post(f"/api/v1/shipments/{sid}/depart", headers=logistics_headers, json={})
    upd = dep.json()["data"]["shipment"]["updated_at"]
    ok = await client.patch(f"/api/v1/shipments/{sid}", headers=logistics_headers, json={
        "bl_no": "MBLLONG123", "eta": "2026-10-01", "note": "已签提单",
        "expected_updated_at": upd})
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["shipment"]["bl_no"] == "MBLLONG123"
    upd2 = ok.json()["data"]["shipment"]["updated_at"]
    bad = await client.patch(f"/api/v1/shipments/{sid}", headers=logistics_headers, json={
        "vessel_name": "OTHER", "expected_updated_at": upd2})
    assert bad.status_code == 400 and bad.json()["code"] == 42005
    assert "vessel_name" in bad.json()["data"]["fields"]


async def test_field_gate_diff_unchanged_value_passes(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """diff 语义:LOADED 态回显整对象(含不可改的 container_no 原值)—— 值未变即放行,不误拒。"""
    d = await make_loadable_shipment(client, db_session, sales_headers, purchaser_headers,
                                     logistics_headers)
    sid = d["shipment"]["id"]
    # 建柜时带柜号,装柜后回显整对象(柜号原值 + 改船名)。
    await client.patch(f"/api/v1/shipments/{sid}", headers=logistics_headers,
                       json={"container_no": "KEEP0001111", "container_type": "40HQ",
                             "expected_updated_at": d["shipment"]["updated_at"]})
    load = await client.post(f"/api/v1/shipments/{sid}/load", headers=logistics_headers, json={})
    upd = load.json()["data"]["shipment"]["updated_at"]
    # 全量 payload 回显不可改字段的原值 + 改可改字段 → 放行(值未变不拒)。
    r = await client.patch(f"/api/v1/shipments/{sid}", headers=logistics_headers, json={
        "container_no": "KEEP0001111", "container_type": "40HQ",   # 不可改但值未变
        "vessel_name": "COSCO", "expected_updated_at": upd})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["shipment"]["vessel_name"] == "COSCO"


async def test_edit_optimistic_lock_42006(client, logistics_headers):
    """陈旧 expected_updated_at → 42006(编辑冲突,独立于非法转移/字段门禁)。"""
    ship = await create_shipment(client, logistics_headers)
    r = await client.patch(f"/api/v1/shipments/{ship['id']}", headers=logistics_headers, json={
        "vessel_name": "X", "expected_updated_at": "2000-01-01T00:00:00"})
    assert r.status_code == 409 and r.json()["code"] == 42006


# ---------- 离港 atd 默认/显式 ----------


async def test_depart_default_today(client, db_session, sales_headers, purchaser_headers,
                                    logistics_headers):
    """离港确认不带 atd → 默认当日(UTC)。"""
    d = await make_loadable_shipment(client, db_session, sales_headers, purchaser_headers,
                                     logistics_headers)
    sid = d["shipment"]["id"]
    await client.post(f"/api/v1/shipments/{sid}/load", headers=logistics_headers, json={})
    dp = await client.post(f"/api/v1/shipments/{sid}/depart", headers=logistics_headers, json={})
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    assert dp.json()["data"]["shipment"]["atd"] == today


async def test_depart_explicit_atd(client, db_session, sales_headers, purchaser_headers,
                                   logistics_headers):
    """离港确认带显式 atd(早于 etd 合法:提前离港)→ 采用该值。"""
    d = await make_loadable_shipment(client, db_session, sales_headers, purchaser_headers,
                                     logistics_headers)
    sid = d["shipment"]["id"]
    await client.post(f"/api/v1/shipments/{sid}/load", headers=logistics_headers, json={})
    dp = await client.post(f"/api/v1/shipments/{sid}/depart", headers=logistics_headers,
                           json={"atd": "2026-07-01"})
    assert dp.status_code == 200
    assert dp.json()["data"]["shipment"]["atd"] == "2026-07-01"


# ---------- 发运全程库存不变(回归) ----------


async def test_shipment_lifecycle_does_not_touch_stock(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """发运不碰库存:装柜/离港/撤离港/撤装柜全程 compute_stock_balance 可发量恒定
    (可发只随出库 ISSUED 变,发运动作零影响)。"""
    d = await make_loadable_shipment(client, db_session, sales_headers, purchaser_headers,
                                     logistics_headers, qty=6)
    sid = d["shipment"]["id"]
    so_id, sku_id = d["sales_order_id"], d["so_lines"][0]["sku_id"]
    # 出库已发 6,收货 10 → 可发基线 4。
    base = await _available(client, logistics_headers, so_id, sku_id)
    assert base == 4.0
    for path, body in (("load", {}), ("depart", {}), ("undepart", None),
                       ("unload", None)):
        r = await client.post(f"/api/v1/shipments/{sid}/{path}", headers=logistics_headers,
                              json=body if body is not None else None)
        assert r.status_code == 200, (path, r.text)
        assert await _available(client, logistics_headers, so_id, sku_id) == base


# ---------- RBAC ----------


async def test_rbac_sales_read_only_403_on_shipment_actions(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """SALES 只读:发运写动作(load/unload/depart/undepart/patch)全 403;LOGISTICS 可写。"""
    d = await make_loadable_shipment(client, db_session, sales_headers, purchaser_headers,
                                     logistics_headers)
    sid = d["shipment"]["id"]
    for path in ("load", "depart", "unload", "undepart"):
        r = await client.post(f"/api/v1/shipments/{sid}/{path}", headers=sales_headers, json={})
        assert r.status_code == 403, (path, r.text)
    patch = await client.patch(f"/api/v1/shipments/{sid}", headers=sales_headers,
                               json={"vessel_name": "X",
                                     "expected_updated_at": d["shipment"]["updated_at"]})
    assert patch.status_code == 403
    # SALES 读可达。
    assert (await client.get(f"/api/v1/shipments/{sid}", headers=sales_headers)).status_code == 200
    # LOGISTICS 可写(装柜确认)。
    assert (await client.post(f"/api/v1/shipments/{sid}/load", headers=logistics_headers,
                              json={})).status_code == 200


# ---------- 稀疏 PATCH:未传字段不动、乐观锁必填(API 级入口,前端全量 payload 覆盖不到) ----------


async def test_partial_patch_preserves_untouched_fields(client, logistics_headers):
    """局部 PATCH 只改传入字段,未传字段保持原值(不被 None 覆盖清空)。"""
    ship = await create_shipment(client, logistics_headers,
                                 container_no="AAAU1111111", vessel_name="EVER GIVEN",
                                 booking_no="BK1")
    r = await client.patch(f"/api/v1/shipments/{ship['id']}", headers=logistics_headers,
                           json={"vessel_name": "MSC", "expected_updated_at": ship["updated_at"]})
    assert r.status_code == 200, r.text
    b = r.json()["data"]["shipment"]
    assert b["vessel_name"] == "MSC"          # 改了
    assert b["container_no"] == "AAAU1111111"  # 未传 → 保持,不被清空
    assert b["booking_no"] == "BK1"            # 未传 → 保持


async def test_partial_patch_on_loaded_ignores_untouched_locked_field(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """LOADED 柜已有 container_no 时,局部 PATCH 只改船务字段 → 不误报 42005
    (未传的锁定字段 container_no 不参与 diff)。"""
    d = await make_loadable_shipment(client, db_session, sales_headers, purchaser_headers,
                                     logistics_headers)
    sid = d["shipment"]["id"]
    # OPEN 期先落一个 container_no。
    await client.patch(f"/api/v1/shipments/{sid}", headers=logistics_headers,
                       json={"container_no": "BMOU2222222",
                             "expected_updated_at": d["shipment"]["updated_at"]})
    load = await client.post(f"/api/v1/shipments/{sid}/load", headers=logistics_headers, json={})
    upd = load.json()["data"]["shipment"]["updated_at"]
    # 仅改船务字段(不带 container_no)→ 应 200,不因锁定的 container_no 误报 42005。
    r = await client.patch(f"/api/v1/shipments/{sid}", headers=logistics_headers,
                           json={"vessel_name": "COSCO", "expected_updated_at": upd})
    assert r.status_code == 200, r.text
    b = r.json()["data"]["shipment"]
    assert b["vessel_name"] == "COSCO" and b["container_no"] == "BMOU2222222"


async def test_patch_missing_expected_updated_at_422(client, logistics_headers):
    """乐观锁基线必填(对齐入库/出库/PO):漏传 expected_updated_at → 422,不退回无锁覆盖。"""
    ship = await create_shipment(client, logistics_headers)
    r = await client.patch(f"/api/v1/shipments/{ship['id']}", headers=logistics_headers,
                           json={"vessel_name": "X"})
    assert r.status_code == 422, r.text
