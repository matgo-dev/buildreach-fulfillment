"""SO 整单取消(契约 2026-07-16-0707 v2):契约 13 锚点,本文件落 12 测试(锚点 10 除外)。

骨架:CONFIRMED→CANCELLED + 报价 CONVERTED→LOCKED 回退可重转;下游活动 PO 硬拦(41802);
不级联;偏唯一(仅活动 SO 占报价);报价删行/删单引用保护(41411);lock 端点仅 DRAFT(B1)。
锚点 10 = B2(取消 vs 建 PO TOCTOU 并发交错),由 _load_source_so_lines 锁 SO 头闭环——
同型先例入库↔PO 取消,锁序无环(建单 SO头→SO行;取消 SO头→报价头;convert 仅报价头),
不做进程内并发编排测试,以锚点 8(取消后建 PO 被拒)+ 代码内 with_for_update 保障。
"""
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.db.models.audit_log import AuditLog
from app.db.models.sales_order import SalesOrderLine
from tests.outbound_helpers import create_outbound, create_shipment
from tests.purchase_helpers import (
    create_supplier,
    make_confirmed_sales_order,
    seed_catalog_and_customer,
)

pytestmark = pytest.mark.asyncio


async def _make_so(client, sales_headers, db_session, *, qty=10):
    cust, sku = await seed_catalog_and_customer(db_session)
    so_id, so_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": "9.00", "qty": qty}])
    so = (await client.get(f"/api/v1/sales-orders/{so_id}",
                           headers=sales_headers)).json()["data"]["order"]
    return so, so_lines


async def _cancel(client, headers, so_id, reason=None):
    return await client.post(f"/api/v1/sales-orders/{so_id}/cancel", headers=headers,
                             json={"reason": reason})


# ---------- 锚点 1:取消成功 = SO 终态 + 留痕 + 报价回 LOCKED ----------

async def test_cancel_success_and_quotation_reverts(client, db_session, sales_headers):
    so, _ = await _make_so(client, sales_headers, db_session)
    r = await _cancel(client, sales_headers, so["id"], reason="客户毁单")
    assert r.status_code == 200, r.text
    order = r.json()["data"]["order"]
    assert order["status"] == "CANCELLED"

    detail = (await client.get(f"/api/v1/sales-orders/{so['id']}",
                               headers=sales_headers)).json()["data"]["order"]
    assert detail["status"] == "CANCELLED"

    q = (await client.get(f"/api/v1/quotations/{so['source_quotation_id']}",
                          headers=sales_headers)).json()["data"]["order"]
    assert q["status"] == "LOCKED"
    assert q["sales_order"] is None  # 反查仅 CONVERTED 下发


# ---------- 锚点 2:活动 PO 硬拦 → 全取消后放行 ----------

async def test_cancel_blocked_by_active_po_then_allowed(
        client, db_session, sales_headers, purchaser_headers):
    so, so_lines = await _make_so(client, sales_headers, db_session)
    sup = await create_supplier(client, purchaser_headers)
    po = (await client.post("/api/v1/purchase-orders", headers=purchaser_headers, json={
        "source_sales_order_id": so["id"], "supplier_id": sup["id"], "currency": "USD",
        "lines": [{"source_sales_order_line_id": so_lines[0]["id"], "qty": 3,
                   "unit_price": 5}]})).json()["data"]["order"]

    r = await _cancel(client, sales_headers, so["id"])  # DRAFT PO 也算活动
    assert r.status_code == 409 and r.json()["code"] == 41802

    await client.post(f"/api/v1/purchase-orders/{po['id']}/cancel", headers=purchaser_headers)
    r2 = await _cancel(client, sales_headers, so["id"])
    assert r2.status_code == 200, r2.text


# ---------- 锚点 2b:活动出库单硬拦(含 DRAFT 草稿)→ 全取消后放行 ----------
# 出库单不经采购/收货即可建 DRAFT(create_order 不校验可发库存,只校验 SO/柜状态),
# 故用最小链路复现:草稿出库单未扣库存,但仍是「指向本 SO 的活动下游单据」,
# 放行会留下一张挂在已取消 SO 下的活动出库单(悬空引用)。

async def test_cancel_blocked_by_active_outbound_then_allowed(
        client, db_session, sales_headers, logistics_headers):
    so, so_lines = await _make_so(client, sales_headers, db_session)
    ship = await create_shipment(client, logistics_headers)
    cr = await create_outbound(client, logistics_headers, sales_order_id=so["id"],
                               shipment_id=ship["id"],
                               lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 1}])
    assert cr.status_code == 200, cr.text
    ob_id = cr.json()["data"]["order"]["id"]

    r = await _cancel(client, sales_headers, so["id"])  # DRAFT 出库单也算活动
    assert r.status_code == 409 and r.json()["code"] == 41803

    await client.post(f"/api/v1/outbound-orders/{ob_id}/cancel", headers=logistics_headers)
    r2 = await _cancel(client, sales_headers, so["id"])
    assert r2.status_code == 200, r2.text


# ---------- 锚点 3:重复取消 → 41801 ----------

async def test_cancel_twice_rejected(client, db_session, sales_headers):
    so, _ = await _make_so(client, sales_headers, db_session)
    assert (await _cancel(client, sales_headers, so["id"])).status_code == 200
    r = await _cancel(client, sales_headers, so["id"])
    assert r.status_code == 409 and r.json()["code"] == 41801


# ---------- 锚点 4:重转 —— 报价回 LOCKED 后可再 convert,反查指向新 SO ----------

async def test_reconvert_after_cancel(client, db_session, sales_headers):
    so, _ = await _make_so(client, sales_headers, db_session)
    qid = so["source_quotation_id"]
    assert (await _cancel(client, sales_headers, so["id"])).status_code == 200

    conv = await client.post(f"/api/v1/quotations/{qid}/convert", headers=sales_headers)
    assert conv.status_code == 200, conv.text
    new_so = conv.json()["data"]["order"]
    assert new_so["id"] != so["id"]

    # 反查只认活动行(新 SO);旧 CANCELLED 行与新行共存(偏唯一放行)
    q = (await client.get(f"/api/v1/quotations/{qid}",
                          headers=sales_headers)).json()["data"]["order"]
    assert q["status"] == "CONVERTED"
    assert q["sales_order"]["id"] == new_so["id"]
    old = (await client.get(f"/api/v1/sales-orders/{so['id']}",
                            headers=sales_headers)).json()["data"]["order"]
    assert old["status"] == "CANCELLED"


# ---------- 锚点 5:行级复合 UNIQUE —— 同单内重复报价行仍被 DB 拒 ----------

async def test_line_composite_unique_blocks_same_order_dup(client, db_session, sales_headers):
    so, _ = await _make_so(client, sales_headers, db_session)
    line = (await db_session.execute(select(SalesOrderLine).where(
        SalesOrderLine.sales_order_id == so["id"]))).scalars().first()
    db_session.add(SalesOrderLine(
        sales_order_id=line.sales_order_id, sku_id=line.sku_id,
        source_quotation_line_id=line.source_quotation_line_id,
        name_snapshot=line.name_snapshot, spec_text_snapshot=line.spec_text_snapshot,
        unit_snapshot=line.unit_snapshot, unit_price=line.unit_price, qty=line.qty,
        line_total=line.line_total, language=line.language, sort_order=99))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


# ---------- 锚点 6:RBAC —— PURCHASER / ADMIN 均无 sales:manage ----------

async def test_cancel_rbac_denied(client, db_session, sales_headers,
                                  purchaser_headers, superadmin_headers):
    so, _ = await _make_so(client, sales_headers, db_session)
    assert (await _cancel(client, purchaser_headers, so["id"])).status_code == 403
    assert (await _cancel(client, superadmin_headers, so["id"])).status_code == 403


# ---------- 锚点 7:审计两行 extra 互指 ----------

async def test_cancel_audit_cross_referenced(client, db_session, sales_headers):
    so, _ = await _make_so(client, sales_headers, db_session)
    assert (await _cancel(client, sales_headers, so["id"])).status_code == 200

    cancel_row = (await db_session.execute(select(AuditLog).where(
        AuditLog.resource_type == "sales_order", AuditLog.action == "CANCEL",
        AuditLog.resource_id == str(so["id"])))).scalars().one()
    assert cancel_row.extra == {"quotation_id": so["source_quotation_id"]}
    unconvert_row = (await db_session.execute(select(AuditLog).where(
        AuditLog.resource_type == "quotation", AuditLog.action == "UNCONVERT",
        AuditLog.resource_id == str(so["source_quotation_id"])))).scalars().one()
    assert unconvert_row.extra == {"sales_order_id": so["id"]}


# ---------- 锚点 8:取消后建 PO 被拒(41604,现有守卫回归) ----------

async def test_po_create_on_cancelled_so_rejected(
        client, db_session, sales_headers, purchaser_headers):
    so, so_lines = await _make_so(client, sales_headers, db_session)
    assert (await _cancel(client, sales_headers, so["id"])).status_code == 200
    sup = await create_supplier(client, purchaser_headers)
    r = await client.post("/api/v1/purchase-orders", headers=purchaser_headers, json={
        "source_sales_order_id": so["id"], "supplier_id": sup["id"], "currency": "USD",
        "lines": [{"source_sales_order_line_id": so_lines[0]["id"], "qty": 1,
                   "unit_price": 5}]})
    assert r.status_code == 404 and r.json()["code"] == 41604


# ---------- 锚点 9:B1 —— 公开 lock 端点对 CONVERTED 收紧 ----------

async def test_lock_converted_quotation_rejected(client, db_session, sales_headers):
    so, _ = await _make_so(client, sales_headers, db_session)
    r = await client.post(f"/api/v1/quotations/{so['source_quotation_id']}/lock",
                          headers=sales_headers)
    assert r.status_code == 409 and r.json()["code"] == 41401


# ---------- 锚点 10:B2 并发交错 —— 不落进程内编排测试,见模块 docstring ----------

# ---------- 锚点 11:S1 —— 报价回 LOCKED 后删行引用保护;改量放行可重转 ----------

async def test_quotation_edit_after_cancel_reference_guard(client, db_session, sales_headers):
    so, _ = await _make_so(client, sales_headers, db_session)
    qid = so["source_quotation_id"]
    assert (await _cancel(client, sales_headers, so["id"])).status_code == 200
    assert (await client.post(f"/api/v1/quotations/{qid}/unlock",
                              headers=sales_headers)).status_code == 200

    d = (await client.get(f"/api/v1/quotations/{qid}", headers=sales_headers)).json()["data"]
    q, qlines = d["order"], d["lines"]

    def _body(lines):
        return {"customer_id": q["customer_id"], "currency": q["currency"],
                "summary": q["summary"], "expected_updated_at": q["updated_at"],
                "lines": lines}

    # 删被引用行(payload 缺席 = DELETE)→ 41411(行级引用保护;整单已无硬删,退役走作废)
    r = await client.put(f"/api/v1/quotations/{qid}", headers=sales_headers, json=_body([]))
    assert r.status_code == 409 and r.json()["code"] == 41411, r.text

    # 改数量/价格(UPDATE 不触 FK)→ 放行,且可重锁重转
    edited = [{"id": qlines[0]["id"], "sku_id": qlines[0]["sku_id"],
               "unit_price": 8.5, "qty": 6, "sort_order": 0}]
    r = await client.put(f"/api/v1/quotations/{qid}", headers=sales_headers, json=_body(edited))
    assert r.status_code == 200, r.text
    assert (await client.post(f"/api/v1/quotations/{qid}/lock",
                              headers=sales_headers)).status_code == 200
    conv = await client.post(f"/api/v1/quotations/{qid}/convert", headers=sales_headers)
    assert conv.status_code == 200, conv.text
    assert float(conv.json()["data"]["order"]["total_amount"]) == 51.0  # 8.5×6


# ---------- 锚点 12:S3 —— purchasable_only 服务端排除 CANCELLED ----------

async def test_purchasable_only_excludes_cancelled(client, db_session, sales_headers):
    so, _ = await _make_so(client, sales_headers, db_session)
    assert (await _cancel(client, sales_headers, so["id"])).status_code == 200
    r = await client.get("/api/v1/sales-orders", headers=sales_headers,
                         params={"purchasable_only": "true"})  # 不带 status,考服务端语义
    ids = [it["id"] for it in r.json()["data"]["items"]]
    assert so["id"] not in ids


# ---------- 锚点 13:N1 —— CHECK 留痕轴与状态一致 ----------

async def test_cancel_trace_check_constraint(client, db_session, sales_headers):
    """裸置 CANCELLED 不带 cancelled_at → 违约束;带齐留痕 → 放行(区分新旧 CHECK 语义)。"""
    so, _ = await _make_so(client, sales_headers, db_session)
    # 正半边:status + cancelled_at 同置 → 新 CHECK 放行(旧 CHECK status IN ('CONFIRMED') 会拒)
    await db_session.execute(text(
        "UPDATE sales_orders SET status='CANCELLED', cancelled_at=now() WHERE id=:i"),
        {"i": so["id"]})
    await db_session.execute(text(
        "UPDATE sales_orders SET status='CONFIRMED', cancelled_at=NULL WHERE id=:i"),
        {"i": so["id"]})
    # 负半边:裸置 CANCELLED 不带留痕 → 违 ck_sorders_cancel_trace
    with pytest.raises(IntegrityError):
        await db_session.execute(text(
            "UPDATE sales_orders SET status = 'CANCELLED' WHERE id = :i"), {"i": so["id"]})
    await db_session.rollback()
