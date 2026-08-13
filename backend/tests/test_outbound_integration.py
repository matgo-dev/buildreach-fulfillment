"""出库单主流程 + 全错误路径 + 应收生成/幂等/舍入/出库终点(契约 §6)。"""
import pytest
from sqlalchemy import select

from app.db.models.receivable import Receivable
from tests.inventory_helpers import find_line
from tests.outbound_helpers import (
    create_and_confirm_outbound,
    create_outbound,
    create_shipment,
    setup_available_stock,
)

pytestmark = pytest.mark.asyncio


# ---------- 建单守卫 ----------


async def test_create_requires_confirmed_so(client, db_session, sales_headers,
                                            purchaser_headers, logistics_headers):
    """SO 非 CONFIRMED(取消)→ 41905。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers,
                                      so_qty=10, received=0)
    so_id, so_lines = ctx["sales_order_id"], ctx["so_lines"]
    ship = await create_shipment(client, logistics_headers)
    # 取消 SO(无活动 PO 前提:需先取消 PO)。先取消 PO 再取消 SO。
    await client.post(f"/api/v1/purchase-orders/{ctx['purchase_order_id']}/cancel",
                      headers=purchaser_headers)
    await client.post(f"/api/v1/sales-orders/{so_id}/cancel", headers=sales_headers,
                      json={"reason": "x"})
    r = await create_outbound(client, logistics_headers, sales_order_id=so_id,
                              shipment_id=ship["id"],
                              lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 1}])
    assert r.status_code == 409 and r.json()["code"] == 41905


async def test_create_requires_open_shipment(client, db_session, sales_headers,
                                             purchaser_headers, logistics_headers):
    """柜非 OPEN(已取消)→ 41906。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers)
    ship = await create_shipment(client, logistics_headers)
    await client.post(f"/api/v1/shipments/{ship['id']}/cancel", headers=logistics_headers)
    r = await create_outbound(client, logistics_headers, sales_order_id=ctx["sales_order_id"],
                              shipment_id=ship["id"],
                              lines=[{"sales_order_line_id": ctx["so_lines"][0]["id"], "qty": 1}])
    assert r.status_code == 409 and r.json()["code"] == 41906


async def test_create_line_not_in_so(client, db_session, sales_headers, purchaser_headers,
                                     logistics_headers):
    """行 sales_order_line_id 不属于该 SO → 41903。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers)
    ship = await create_shipment(client, logistics_headers)
    r = await create_outbound(client, logistics_headers, sales_order_id=ctx["sales_order_id"],
                              shipment_id=ship["id"],
                              lines=[{"sales_order_line_id": 999999, "qty": 1}])
    assert r.status_code == 400 and r.json()["code"] == 41903


async def test_create_duplicate_line_rejected(client, db_session, sales_headers,
                                              purchaser_headers, logistics_headers):
    """payload 同一 SO 行重复 → 41909(前置友好错,不打穿 DB UNIQUE 成 500);编辑同拒。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers)
    so_id, so_lines = ctx["sales_order_id"], ctx["so_lines"]
    ship = await create_shipment(client, logistics_headers)
    r = await create_outbound(client, logistics_headers, sales_order_id=so_id,
                              shipment_id=ship["id"],
                              lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 2},
                                     {"sales_order_line_id": so_lines[0]["id"], "qty": 3}])
    assert r.status_code == 400 and r.json()["code"] == 41909
    # 编辑路径同守卫。
    cr = await create_outbound(client, logistics_headers, sales_order_id=so_id,
                               shipment_id=ship["id"],
                               lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 2}])
    order = cr.json()["data"]["order"]
    r2 = await client.put(f"/api/v1/outbound-orders/{order['id']}", headers=logistics_headers,
                          json={"lines": [{"sales_order_line_id": so_lines[0]["id"], "qty": 1},
                                          {"sales_order_line_id": so_lines[0]["id"], "qty": 2}],
                                "expected_updated_at": order["updated_at"]})
    assert r2.status_code == 400 and r2.json()["code"] == 41909


async def test_create_draft_order_exists(client, db_session, sales_headers, purchaser_headers,
                                         logistics_headers):
    """同柜同 SO 已有 DRAFT 出库单 → 41904;取消草稿后可重开。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers)
    so_id, so_lines = ctx["sales_order_id"], ctx["so_lines"]
    ship = await create_shipment(client, logistics_headers)
    r1 = await create_outbound(client, logistics_headers, sales_order_id=so_id,
                               shipment_id=ship["id"],
                               lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 1}])
    assert r1.status_code == 200
    r2 = await create_outbound(client, logistics_headers, sales_order_id=so_id,
                               shipment_id=ship["id"],
                               lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 1}])
    assert r2.status_code == 409 and r2.json()["code"] == 41904
    # 取消第一张后可重开。
    ob1 = r1.json()["data"]["order"]["id"]
    await client.post(f"/api/v1/outbound-orders/{ob1}/cancel", headers=logistics_headers)
    r3 = await create_outbound(client, logistics_headers, sales_order_id=so_id,
                               shipment_id=ship["id"],
                               lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 1}])
    assert r3.status_code == 200, r3.text


async def test_create_empty_lines_422(client, db_session, sales_headers, purchaser_headers,
                                      logistics_headers):
    """空行 payload → 422(schema min_length=1)。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers)
    ship = await create_shipment(client, logistics_headers)
    r = await client.post("/api/v1/outbound-orders", headers=logistics_headers, json={
        "sales_order_id": ctx["sales_order_id"], "shipment_id": ship["id"], "lines": []})
    assert r.status_code == 422


# ---------- 确认出库:库存闸 ----------


async def test_confirm_insufficient_available(client, db_session, sales_headers,
                                              purchaser_headers, logistics_headers):
    """本单需发 > 可发 → 41902,biz_data 带逐 sku 明细。"""
    # 收货 4,可发 4;出库单要发 6。
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers,
                                      so_qty=10, received=4)
    so_id, so_lines = ctx["sales_order_id"], ctx["so_lines"]
    ship = await create_shipment(client, logistics_headers)
    cr = await create_outbound(client, logistics_headers, sales_order_id=so_id,
                               shipment_id=ship["id"],
                               lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 6}])
    ob_id = cr.json()["data"]["order"]["id"]
    conf = await client.post(f"/api/v1/outbound-orders/{ob_id}/confirm", headers=logistics_headers)
    assert conf.status_code == 409 and conf.json()["code"] == 41902
    items = conf.json()["data"]["items"]
    assert items[0]["required_qty"] == 6.0 and items[0]["available_qty"] == 4.0


async def test_double_outbound_over_issue_rejected(client, db_session, sales_headers,
                                                   purchaser_headers, logistics_headers):
    """并发双出库超发(库存契约预订用例,顺序化验证):可发 10,第一张发 7 确认,
    第二张发 4 确认 → 41902(锁内派生只见已 ISSUED 的 7,剩 3 < 4)。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers,
                                      so_qty=10, received=10)
    so_id, so_lines = ctx["sales_order_id"], ctx["so_lines"]
    ship1 = await create_shipment(client, logistics_headers)
    ship2 = await create_shipment(client, logistics_headers)
    _, c1 = await create_and_confirm_outbound(
        client, logistics_headers, sales_order_id=so_id, shipment_id=ship1["id"],
        lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 7}])
    assert c1.status_code == 200, c1.text
    _, c2 = await create_and_confirm_outbound(
        client, logistics_headers, sales_order_id=so_id, shipment_id=ship2["id"],
        lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 4}])
    assert c2.status_code == 409 and c2.json()["code"] == 41902


async def test_append_outbound_after_issued_same_shipment_allowed(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """同柜同 SO 已有 ISSUED 后,允许再建一张 DRAFT 追加出库;
    但同一时间仍只能有一张未确认草稿。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers,
                                      so_qty=30, received=30)
    so_id, so_lines = ctx["sales_order_id"], ctx["so_lines"]
    ship = await create_shipment(client, logistics_headers)

    _, c1 = await create_and_confirm_outbound(
        client, logistics_headers, sales_order_id=so_id, shipment_id=ship["id"],
        lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 10}])
    assert c1.status_code == 200, c1.text

    r2 = await create_outbound(client, logistics_headers, sales_order_id=so_id,
                               shipment_id=ship["id"],
                               lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 10}])
    assert r2.status_code == 200, r2.text
    ob2 = r2.json()["data"]["order"]
    assert ob2["status"] == "DRAFT"

    r3 = await create_outbound(client, logistics_headers, sales_order_id=so_id,
                               shipment_id=ship["id"],
                               lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 1}])
    assert r3.status_code == 409 and r3.json()["code"] == 41904

    c2 = await client.post(f"/api/v1/outbound-orders/{ob2['id']}/confirm",
                           headers=logistics_headers)
    assert c2.status_code == 200, c2.text
    ol = await client.get(f"/api/v1/sales-orders/{so_id}/outboundable-lines",
                          headers=logistics_headers)
    assert find_line(ol.json()["data"]["items"], so_lines[0]["sku_id"])["available_qty"] == 10.0

    r4 = await create_outbound(client, logistics_headers, sales_order_id=so_id,
                               shipment_id=ship["id"],
                               lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 5}])
    assert r4.status_code == 200, r4.text


async def test_confirm_generates_receivable(client, db_session, sales_headers, purchaser_headers,
                                            logistics_headers):
    """确认生成应收:金额 = Σ qty×SO行单价;客户/币种取自 SO。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers,
                                      so_qty=10, unit_price="9.00", received=10)
    so_id, so_lines = ctx["sales_order_id"], ctx["so_lines"]
    ship = await create_shipment(client, logistics_headers)
    ob_id, conf = await create_and_confirm_outbound(
        client, logistics_headers, sales_order_id=so_id, shipment_id=ship["id"],
        lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 6}])
    assert conf.status_code == 200
    rows = list((await db_session.execute(
        select(Receivable).where(Receivable.outbound_order_id == ob_id))).scalars().all())
    assert len(rows) == 1
    r = rows[0]
    assert float(r.amount_original) == 54.0    # 6 × 9.00
    assert float(r.amount_allocated) == 0.0
    assert r.customer_id == ctx["customer"].id and r.currency == "USD"
    assert r.voided_at is None


async def test_confirm_idempotent_no_double_receivable(client, db_session, sales_headers,
                                                       purchaser_headers, logistics_headers):
    """重复确认:头锁+转移守卫先挡(41901),应收不双开。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers)
    so_id, so_lines = ctx["sales_order_id"], ctx["so_lines"]
    ship = await create_shipment(client, logistics_headers)
    ob_id, conf = await create_and_confirm_outbound(
        client, logistics_headers, sales_order_id=so_id, shipment_id=ship["id"],
        lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 5}])
    assert conf.status_code == 200
    dup = await client.post(f"/api/v1/outbound-orders/{ob_id}/confirm", headers=logistics_headers)
    assert dup.status_code == 409 and dup.json()["code"] == 41901
    rows = list((await db_session.execute(
        select(Receivable).where(Receivable.outbound_order_id == ob_id))).scalars().all())
    assert len(rows) == 1


async def test_receivable_amount_rounding_half_up(client, db_session, sales_headers,
                                                  purchaser_headers, logistics_headers):
    """逐行 quantize ROUND_HALF_UP:qty1.5 × 0.03 = 0.045 → 0.05(half-even 会得 0.04)。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers,
                                      so_qty=2, unit_price="0.03", received=2)
    so_id, so_lines = ctx["sales_order_id"], ctx["so_lines"]
    ship = await create_shipment(client, logistics_headers)
    ob_id, conf = await create_and_confirm_outbound(
        client, logistics_headers, sales_order_id=so_id, shipment_id=ship["id"],
        lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 1.5}])
    assert conf.status_code == 200, conf.text
    r = (await db_session.execute(
        select(Receivable).where(Receivable.outbound_order_id == ob_id))).scalar_one()
    assert float(r.amount_original) == 0.05


async def test_zero_amount_receivable_is_paid(client, db_session, sales_headers,
                                              purchaser_headers, logistics_headers):
    """SO 行单价 0 → 应收原值 0 → 派生状态 PAID(余额 0 无欠款,不永远未收)。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers,
                                      so_qty=5, unit_price="0.00", received=5)
    so_id, so_lines = ctx["sales_order_id"], ctx["so_lines"]
    ship = await create_shipment(client, logistics_headers)
    ob_id, conf = await create_and_confirm_outbound(
        client, logistics_headers, sales_order_id=so_id, shipment_id=ship["id"],
        lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 5}])
    assert conf.status_code == 200, conf.text
    r = (await db_session.execute(
        select(Receivable).where(Receivable.outbound_order_id == ob_id))).scalar_one()
    assert float(r.amount_original) == 0.0
    from app.db.models.receivable import ReceivableStatus, derive_receivable_status
    assert derive_receivable_status(r.amount_original, r.amount_allocated) == ReceivableStatus.PAID


# ---------- 已出库终点 ----------


async def test_revert_issued_rejected_keeps_receivable_and_stock(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """0811:ISSUED 是正向终点;旧撤销入口拒绝,且不作废应收/不恢复可发。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers,
                                      so_qty=10, received=10)
    so_id, so_lines = ctx["sales_order_id"], ctx["so_lines"]
    ship = await create_shipment(client, logistics_headers)
    ob_id, conf = await create_and_confirm_outbound(
        client, logistics_headers, sales_order_id=so_id, shipment_id=ship["id"],
        lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 6}])
    assert conf.status_code == 200
    rev = await client.post(f"/api/v1/outbound-orders/{ob_id}/revert", headers=logistics_headers,
                            json={"void_reason": "装错柜"})
    assert rev.status_code == 409 and rev.json()["code"] == 41901
    detail = await client.get(f"/api/v1/outbound-orders/{ob_id}", headers=logistics_headers)
    assert detail.json()["data"]["order"]["status"] == "ISSUED"
    assert detail.json()["data"]["order"]["issued_at"] is not None
    # 应收仍为活动行。
    r = (await db_session.execute(
        select(Receivable).where(Receivable.outbound_order_id == ob_id))).scalar_one()
    assert r.voided_at is None
    # 可发仍为 4。
    ol = await client.get(f"/api/v1/sales-orders/{so_id}/outboundable-lines",
                          headers=logistics_headers)
    assert find_line(ol.json()["data"]["items"], so_lines[0]["sku_id"])["available_qty"] == 4.0


async def test_revert_issued_rejected_even_when_receivable_allocated(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """0811:是否核销不再决定出库能否撤销;已出库统一不可回退原流程。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers)
    so_id, so_lines = ctx["sales_order_id"], ctx["so_lines"]
    ship = await create_shipment(client, logistics_headers)
    ob_id, conf = await create_and_confirm_outbound(
        client, logistics_headers, sales_order_id=so_id, shipment_id=ship["id"],
        lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 5}])
    assert conf.status_code == 200
    r = (await db_session.execute(
        select(Receivable).where(Receivable.outbound_order_id == ob_id))).scalar_one()
    r.amount_allocated = 10
    await db_session.commit()
    rev = await client.post(f"/api/v1/outbound-orders/{ob_id}/revert", headers=logistics_headers,
                            json={})
    assert rev.status_code == 409 and rev.json()["code"] == 41901


# ---------- 草稿编辑:乐观锁 ----------


async def test_draft_save_optimistic_lock_conflict(client, db_session, sales_headers,
                                                   purchaser_headers, logistics_headers):
    """陈旧 expected_updated_at → 409(独立 outbound 编辑冲突码 41908)。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers)
    so_id, so_lines = ctx["sales_order_id"], ctx["so_lines"]
    ship = await create_shipment(client, logistics_headers)
    cr = await create_outbound(client, logistics_headers, sales_order_id=so_id,
                               shipment_id=ship["id"],
                               lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 3}])
    ob_id = cr.json()["data"]["order"]["id"]
    r = await client.put(f"/api/v1/outbound-orders/{ob_id}", headers=logistics_headers, json={
        "lines": [{"sales_order_line_id": so_lines[0]["id"], "qty": 4}],
        "expected_updated_at": "2000-01-01T00:00:00"})
    assert r.status_code == 409 and r.json()["code"] == 41908


async def test_draft_save_rewrites_lines(client, db_session, sales_headers, purchaser_headers,
                                         logistics_headers):
    """草稿整单保存:行整表重写(改数量)。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers)
    so_id, so_lines = ctx["sales_order_id"], ctx["so_lines"]
    ship = await create_shipment(client, logistics_headers)
    cr = await create_outbound(client, logistics_headers, sales_order_id=so_id,
                               shipment_id=ship["id"],
                               lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 3}])
    order = cr.json()["data"]["order"]
    r = await client.put(f"/api/v1/outbound-orders/{order['id']}", headers=logistics_headers, json={
        "lines": [{"sales_order_line_id": so_lines[0]["id"], "qty": 8}],
        "expected_updated_at": order["updated_at"]})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["lines"][0]["qty"] == 8.0


async def test_edit_issued_rejected(client, db_session, sales_headers, purchaser_headers,
                                    logistics_headers):
    """已出库单不可编辑 → 41901。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers)
    so_id, so_lines = ctx["sales_order_id"], ctx["so_lines"]
    ship = await create_shipment(client, logistics_headers)
    ob_id, conf = await create_and_confirm_outbound(
        client, logistics_headers, sales_order_id=so_id, shipment_id=ship["id"],
        lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 5}])
    r = await client.put(f"/api/v1/outbound-orders/{ob_id}", headers=logistics_headers, json={
        "lines": [{"sales_order_line_id": so_lines[0]["id"], "qty": 4}],
        "expected_updated_at": conf.json()["data"]["order"]["updated_at"]})
    assert r.status_code == 409 and r.json()["code"] == 41901


async def test_cancel_issued_rejected(client, db_session, sales_headers, purchaser_headers,
                                      logistics_headers):
    """已出库单不可取消,当前系统暂不支持出库后线上冲正 → 41901。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers)
    so_id, so_lines = ctx["sales_order_id"], ctx["so_lines"]
    ship = await create_shipment(client, logistics_headers)
    ob_id, conf = await create_and_confirm_outbound(
        client, logistics_headers, sales_order_id=so_id, shipment_id=ship["id"],
        lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 5}])
    r = await client.post(f"/api/v1/outbound-orders/{ob_id}/cancel", headers=logistics_headers)
    assert r.status_code == 409 and r.json()["code"] == 41901
