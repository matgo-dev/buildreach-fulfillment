"""入库/应付 RBAC 矩阵(锚点 7)。

两级红线:入库单据零成本(设计消除)+ 详情内 PO 摘要成本端点脱敏 + payable 整块门控。
造「仅 inbound:read」视角 = 在本测试事务内摘掉 PURCHASER 的 {inbound:manage, payable:read,
purchase:read_cost}(权限每请求从 DB 加载,SAVEPOINT 回滚不污染其它测试)——等价未来仓库角色。
"""
import pytest
from sqlalchemy import select

from app.db.models.permission import Permission
from app.db.models.role import Role
from app.db.models.role_permission import RolePermission
from tests.inbound_helpers import setup_confirmed_po

pytestmark = pytest.mark.asyncio


async def _strip_perms(db_session, codes):
    role = (await db_session.execute(
        select(Role).where(Role.code == "PURCHASER"))).scalar_one()
    for code in codes:
        perm = (await db_session.execute(
            select(Permission).where(Permission.code == code))).scalar_one()
        rp = (await db_session.execute(select(RolePermission).where(
            RolePermission.role_id == role.id,
            RolePermission.permission_id == perm.id))).scalar_one()
        await db_session.delete(rp)
    await db_session.flush()


async def test_purchaser_full_access(client, db_session, sales_headers, purchaser_headers):
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10, unit_price="5.00")
    cr = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": po_id,
        "lines": [{"purchase_order_line_id": po_lines[0]["id"], "qty": 4}]})
    assert cr.status_code == 200
    inb_id = cr.json()["data"]["order"]["id"]
    await client.post(f"/api/v1/inbound-orders/{inb_id}/receive", headers=purchaser_headers, json={})
    # 列表/详情/应付列表全通;详情见真实 PO 成本 + payable 块。
    assert (await client.get("/api/v1/inbound-orders", headers=purchaser_headers)).status_code == 200
    d = (await client.get(f"/api/v1/inbound-orders/{inb_id}",
                          headers=purchaser_headers)).json()["data"]
    assert float(d["purchase_order"]["total_amount"]) == 50.0   # 有 read_cost
    assert d["payable"]["amount_original"] == 20.0              # 有 payable:read
    assert (await client.get("/api/v1/payables", headers=purchaser_headers)).status_code == 200


async def test_read_only_role_redactions(client, db_session, sales_headers, purchaser_headers):
    """仅 inbound:read 视角:列表/详情通,PO 摘要成本 null,payable 块缺省,建单 403,/payables 403。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10, unit_price="5.00")
    cr = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": po_id,
        "lines": [{"purchase_order_line_id": po_lines[0]["id"], "qty": 4}]})
    inb_id = cr.json()["data"]["order"]["id"]
    await client.post(f"/api/v1/inbound-orders/{inb_id}/receive", headers=purchaser_headers, json={})

    await _strip_perms(db_session, [
        "inbound:manage", "payable:read", "purchase:read_cost"])

    # 列表/详情仍通(有 inbound:read)。
    assert (await client.get("/api/v1/inbound-orders", headers=purchaser_headers)).status_code == 200
    d = (await client.get(f"/api/v1/inbound-orders/{inb_id}",
                          headers=purchaser_headers)).json()["data"]
    # PO 摘要成本脱敏为 null(无 read_cost);数量非红线仍在。
    assert d["purchase_order"]["total_amount"] is None
    # payable 块整体缺省(无 payable:read)。
    assert "payable" not in d
    # 建单 403(无 inbound:manage)。
    cr2 = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": po_id,
        "lines": [{"purchase_order_line_id": po_lines[0]["id"], "qty": 1}]})
    assert cr2.status_code == 403
    # /payables 403(无 payable:read)。
    assert (await client.get("/api/v1/payables", headers=purchaser_headers)).status_code == 403


async def test_sales_cannot_touch_inbound(client, sales_headers):
    """SALES 无 inbound:* / payable:read:入库列表 + 应付列表均 403。"""
    assert (await client.get("/api/v1/inbound-orders", headers=sales_headers)).status_code == 403
    assert (await client.get("/api/v1/payables", headers=sales_headers)).status_code == 403
