"""物流轨迹事件增量(主流程第9步):录/改/软删在途里程碑 + 状态守卫(42008)+ 到港唯一
(42009)+ 事件越柜(42010)+ event_at≥atd + 撤离港守卫(42007)+ 纯派生当前物流状态 + RBAC。

前置:事件仅 DEPARTED 柜可录。锁序:录改删先锁柜头,与 undepart 前置无事件串行化(TOCTOU)。
物流不碰库存/应收(无回归断言必要——事件表天然与库存派生无交)。
"""
import pytest

from tests.outbound_helpers import (
    create_and_confirm_outbound,
    create_shipment,
    make_loadable_shipment,
    setup_available_stock,
)

pytestmark = pytest.mark.asyncio

ATD = "2026-07-18"


async def _load_depart(client, logistics_headers, ship):
    """封柜 + 离港,返回 shipment_id(柜内已有 ISSUED 出库单)。"""
    sid = ship["id"]
    ld = await client.post(f"/api/v1/shipments/{sid}/load", headers=logistics_headers,
                           json={"expected_updated_at": ship["updated_at"]})
    assert ld.status_code == 200, ld.text
    dp = await client.post(f"/api/v1/shipments/{sid}/depart", headers=logistics_headers,
                           json={"atd": ATD})
    assert dp.status_code == 200, dp.text
    return sid


async def _departed(client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """建到 DEPARTED 的柜(可录物流事件)。返回 shipment_id。"""
    d = await make_loadable_shipment(client, db_session, sales_headers, purchaser_headers,
                                     logistics_headers)
    return await _load_depart(client, logistics_headers, d["shipment"])


async def _departed_from_stock(client, logistics_headers, *, so_id, so_line_id, qty=5):
    """从已有可发库存的 SO 造一个 DEPARTED 柜(不重建 catalog,供「同测试建多柜」用)。"""
    ship = await create_shipment(client, logistics_headers)
    _, conf = await create_and_confirm_outbound(
        client, logistics_headers, sales_order_id=so_id, shipment_id=ship["id"],
        lines=[{"sales_order_line_id": so_line_id, "qty": qty}])
    assert conf.status_code == 200, conf.text
    return await _load_depart(client, logistics_headers, ship)


async def _post_event(client, headers, sid, event_type, event_at, **extra):
    return await client.post(f"/api/v1/shipments/{sid}/logistics-events", headers=headers,
                             json={"event_type": event_type, "event_at": event_at, **extra})


# ---------- 录入 + 派生轨迹 ----------


async def test_record_transshipment_then_arrived_full_timeline(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """DEPARTED 柜录中转→到港:详情内联轨迹按序,当前物流状态派生为最新事件。"""
    sid = await _departed(client, db_session, sales_headers, purchaser_headers, logistics_headers)

    # 无事件时:当前物流状态 = 已离港(DEPARTED 派生)。
    det = await client.get(f"/api/v1/shipments/{sid}", headers=logistics_headers)
    assert det.json()["data"]["current_logistics_status"] == "DEPARTED"
    assert det.json()["data"]["logistics_events"] == []

    ts = await _post_event(client, logistics_headers, sid, "TRANSSHIPMENT", "2026-07-22",
                           location="Singapore", note="转船")
    assert ts.status_code == 200, ts.text
    assert ts.json()["data"]["current_logistics_status"] == "TRANSSHIPMENT"

    ar = await _post_event(client, logistics_headers, sid, "ARRIVED", "2026-07-30",
                           location="Mombasa")
    assert ar.status_code == 200, ar.text
    data = ar.json()["data"]
    assert data["current_logistics_status"] == "ARRIVED"
    evs = data["logistics_events"]
    assert [e["event_type"] for e in evs] == ["TRANSSHIPMENT", "ARRIVED"]  # 正序
    assert evs[0]["location"] == "Singapore" and evs[1]["location"] == "Mombasa"


async def test_event_requires_departed_42008(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """非 DEPARTED 柜(OPEN/LOADED)录事件 → 42008。"""
    # OPEN 空柜。
    ship = await create_shipment(client, logistics_headers)
    r = await _post_event(client, logistics_headers, ship["id"], "TRANSSHIPMENT", "2026-07-22")
    assert r.status_code == 409 and r.json()["code"] == 42008, r.text

    # LOADED(未离港)。
    d = await make_loadable_shipment(client, db_session, sales_headers, purchaser_headers,
                                     logistics_headers)
    sid = d["shipment"]["id"]
    await client.post(f"/api/v1/shipments/{sid}/load", headers=logistics_headers,
                      json={"expected_updated_at": d["shipment"]["updated_at"]})
    r2 = await _post_event(client, logistics_headers, sid, "ARRIVED", "2026-07-30")
    assert r2.status_code == 409 and r2.json()["code"] == 42008, r2.text


async def test_arrived_unique_42009(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """到港每柜至多一条活动事件:第二次 ARRIVED → 42009。中转可重复。"""
    sid = await _departed(client, db_session, sales_headers, purchaser_headers, logistics_headers)
    assert (await _post_event(client, logistics_headers, sid, "TRANSSHIPMENT",
                              "2026-07-20")).status_code == 200
    assert (await _post_event(client, logistics_headers, sid, "TRANSSHIPMENT",
                              "2026-07-22")).status_code == 200  # 中转可重复
    assert (await _post_event(client, logistics_headers, sid, "ARRIVED",
                              "2026-07-30")).status_code == 200
    dup = await _post_event(client, logistics_headers, sid, "ARRIVED", "2026-07-31")
    assert dup.status_code == 409 and dup.json()["code"] == 42009, dup.text


async def test_event_at_before_atd_rejected(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """事件业务日早于离港日 atd → 400(防明显脏数据)。"""
    sid = await _departed(client, db_session, sales_headers, purchaser_headers, logistics_headers)
    r = await _post_event(client, logistics_headers, sid, "TRANSSHIPMENT", "2026-07-10")  # < ATD
    assert r.status_code == 400, r.text


async def test_invalid_event_type_422(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """event_type 值域外(如派生态 DEPARTED / 乱值)→ 422(schema Literal 校验)。"""
    sid = await _departed(client, db_session, sales_headers, purchaser_headers, logistics_headers)
    for bad in ("DEPARTED", "LOADED", "FOO"):
        r = await _post_event(client, logistics_headers, sid, bad, "2026-07-22")
        assert r.status_code == 422, (bad, r.text)


# ---------- 改 / 软删 ----------


async def test_update_event_fields(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """稀疏 PATCH 改事件:改地点/日期/类型;未传字段不动。"""
    sid = await _departed(client, db_session, sales_headers, purchaser_headers, logistics_headers)
    cr = await _post_event(client, logistics_headers, sid, "TRANSSHIPMENT", "2026-07-22",
                           location="Colombo", note="orig")
    eid = cr.json()["data"]["logistics_events"][0]["id"]
    r = await client.patch(f"/api/v1/shipments/{sid}/logistics-events/{eid}",
                           headers=logistics_headers,
                           json={"location": "Singapore", "event_at": "2026-07-25"})
    assert r.status_code == 200, r.text
    ev = r.json()["data"]["logistics_events"][0]
    assert ev["location"] == "Singapore" and ev["event_at"] == "2026-07-25"
    assert ev["note"] == "orig"  # 未传 → 保持


async def test_update_event_to_arrived_unique_42009(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """改 event_type 为 ARRIVED 时,若已有活动到港 → 42009(排除自身)。"""
    sid = await _departed(client, db_session, sales_headers, purchaser_headers, logistics_headers)
    await _post_event(client, logistics_headers, sid, "ARRIVED", "2026-07-30")
    cr = await _post_event(client, logistics_headers, sid, "TRANSSHIPMENT", "2026-07-22")
    ts_id = [e for e in cr.json()["data"]["logistics_events"]
             if e["event_type"] == "TRANSSHIPMENT"][0]["id"]
    r = await client.patch(f"/api/v1/shipments/{sid}/logistics-events/{ts_id}",
                           headers=logistics_headers, json={"event_type": "ARRIVED"})
    assert r.status_code == 409 and r.json()["code"] == 42009, r.text


async def test_soft_delete_event_frees_arrived_unique(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """软删到港后:退出偏唯一,可重录到港(旧到港行保留追溯,不挡)。"""
    sid = await _departed(client, db_session, sales_headers, purchaser_headers, logistics_headers)
    cr = await _post_event(client, logistics_headers, sid, "ARRIVED", "2026-07-30")
    eid = cr.json()["data"]["logistics_events"][0]["id"]
    dl = await client.delete(f"/api/v1/shipments/{sid}/logistics-events/{eid}",
                             headers=logistics_headers)
    assert dl.status_code == 200, dl.text
    assert dl.json()["data"]["logistics_events"] == []       # 软删后不再列出
    assert dl.json()["data"]["current_logistics_status"] == "DEPARTED"  # 回到已离港
    # 可重录到港。
    again = await _post_event(client, logistics_headers, sid, "ARRIVED", "2026-08-01")
    assert again.status_code == 200, again.text


async def test_event_not_on_shipment_42010(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """跨柜访问事件(event 属于 A 柜,路径给 B 柜)→ 42010;事件不存在 → 404。
    两个 DEPARTED 柜共享一份库存(避免重建同名 SPU catalog 撞唯一)。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers,
                                      so_qty=20, received=20)
    so_id, so_line_id = ctx["sales_order_id"], ctx["so_lines"][0]["id"]
    sid_a = await _departed_from_stock(client, logistics_headers, so_id=so_id,
                                       so_line_id=so_line_id)
    sid_b = await _departed_from_stock(client, logistics_headers, so_id=so_id,
                                       so_line_id=so_line_id)
    cr = await _post_event(client, logistics_headers, sid_a, "TRANSSHIPMENT", "2026-07-22")
    eid = cr.json()["data"]["logistics_events"][0]["id"]
    # 用 B 柜路径访问 A 柜的事件。
    r = await client.patch(f"/api/v1/shipments/{sid_b}/logistics-events/{eid}",
                           headers=logistics_headers, json={"location": "X"})
    assert r.status_code == 400 and r.json()["code"] == 42010, r.text
    dl = await client.delete(f"/api/v1/shipments/{sid_b}/logistics-events/{eid}",
                             headers=logistics_headers)
    assert dl.status_code == 400 and dl.json()["code"] == 42010
    # 事件不存在 → 404。
    nf = await client.delete(f"/api/v1/shipments/{sid_a}/logistics-events/999999",
                             headers=logistics_headers)
    assert nf.status_code == 404, nf.text


# ---------- 撤离港守卫(42007)+ 纠错通路 ----------


async def test_undepart_blocked_with_active_events_42007(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """柜下有活动事件时撤离港 → 42007;软删全部事件后撤离港通过(纠错通路)。"""
    sid = await _departed(client, db_session, sales_headers, purchaser_headers, logistics_headers)
    cr = await _post_event(client, logistics_headers, sid, "TRANSSHIPMENT", "2026-07-22")
    eid = cr.json()["data"]["logistics_events"][0]["id"]
    blocked = await client.post(f"/api/v1/shipments/{sid}/undepart", headers=logistics_headers)
    assert blocked.status_code == 409 and blocked.json()["code"] == 42007, blocked.text
    # 软删事件后放行。
    await client.delete(f"/api/v1/shipments/{sid}/logistics-events/{eid}",
                        headers=logistics_headers)
    ok = await client.post(f"/api/v1/shipments/{sid}/undepart", headers=logistics_headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["shipment"]["status"] == "LOADED"
    assert ok.json()["data"]["current_logistics_status"] is None  # 非 DEPARTED → None


# ---------- 派生当前物流状态(列表列) ----------


async def test_list_derived_status_column(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """列表派生列:非 DEPARTED 柜 = None;DEPARTED 无事件 = 已离港;有中转 = 中转。"""
    open_ship = await create_shipment(client, logistics_headers)
    sid = await _departed(client, db_session, sales_headers, purchaser_headers, logistics_headers)
    await _post_event(client, logistics_headers, sid, "TRANSSHIPMENT", "2026-07-22")

    lst = await client.get("/api/v1/shipments?size=100", headers=logistics_headers)
    assert lst.status_code == 200, lst.text
    by_id = {it["id"]: it for it in lst.json()["data"]["items"]}
    assert by_id[open_ship["id"]]["current_logistics_status"] is None
    assert by_id[sid]["current_logistics_status"] == "TRANSSHIPMENT"


async def test_list_filter_by_logistics_status(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """物流状态派生筛选:已离港(无事件)/中转/到港各自命中对应柜,不误收其它态与非 DEPARTED 柜。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers,
                                      so_qty=30, received=30)
    so_id, so_line_id = ctx["sales_order_id"], ctx["so_lines"][0]["id"]
    sid_dep = await _departed_from_stock(client, logistics_headers, so_id=so_id,
                                         so_line_id=so_line_id)  # 无事件 → 已离港
    sid_ts = await _departed_from_stock(client, logistics_headers, so_id=so_id,
                                        so_line_id=so_line_id)
    await _post_event(client, logistics_headers, sid_ts, "TRANSSHIPMENT", "2026-07-20")
    sid_ar = await _departed_from_stock(client, logistics_headers, so_id=so_id,
                                        so_line_id=so_line_id)
    await _post_event(client, logistics_headers, sid_ar, "ARRIVED", "2026-07-30")
    open_ship = await create_shipment(client, logistics_headers)

    async def ids(ls: str) -> set[int]:
        r = await client.get(f"/api/v1/shipments?size=100&logistics_status={ls}",
                             headers=logistics_headers)
        assert r.status_code == 200, r.text
        return {it["id"] for it in r.json()["data"]["items"]}

    dep = await ids("DEPARTED")
    assert sid_dep in dep and sid_ts not in dep and sid_ar not in dep and open_ship["id"] not in dep
    ts = await ids("TRANSSHIPMENT")
    assert sid_ts in ts and sid_dep not in ts and sid_ar not in ts
    ar = await ids("ARRIVED")
    assert sid_ar in ar and sid_dep not in ar and sid_ts not in ar


# ---------- RBAC ----------


async def test_rbac_sales_read_only(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """SALES 只读:录/改/删事件全 403;详情轨迹可读(无红线字段,同权可见在途)。"""
    sid = await _departed(client, db_session, sales_headers, purchaser_headers, logistics_headers)
    cr = await _post_event(client, logistics_headers, sid, "TRANSSHIPMENT", "2026-07-22")
    eid = cr.json()["data"]["logistics_events"][0]["id"]

    post = await _post_event(client, sales_headers, sid, "ARRIVED", "2026-07-30")
    assert post.status_code == 403, post.text
    patch = await client.patch(f"/api/v1/shipments/{sid}/logistics-events/{eid}",
                               headers=sales_headers, json={"location": "X"})
    assert patch.status_code == 403
    dl = await client.delete(f"/api/v1/shipments/{sid}/logistics-events/{eid}",
                             headers=sales_headers)
    assert dl.status_code == 403
    # SALES 读可达,轨迹可见。
    det = await client.get(f"/api/v1/shipments/{sid}", headers=sales_headers)
    assert det.status_code == 200
    assert det.json()["data"]["current_logistics_status"] == "TRANSSHIPMENT"
