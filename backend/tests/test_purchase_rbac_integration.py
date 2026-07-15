"""采购域 RBAC:整域门(无 purchase:read 直接 403)+ 建单守 purchase:manage + 可采行门控。

红线两级:整域门(本文件)+ 字段门(采购价/金额脱敏,见 test_purchase_redaction_unit)。
"""
import pytest

from tests.purchase_helpers import (
    create_supplier,
    make_confirmed_sales_order,
    seed_catalog_and_customer,
)


@pytest.mark.asyncio
async def test_sales_cannot_read_purchase_orders(client, sales_headers):
    """SALES 无 purchase:read:PO 列表 403(整域门,采购单不下发给销售)。"""
    assert (await client.get("/api/v1/purchase-orders", headers=sales_headers)).status_code == 403


@pytest.mark.asyncio
async def test_sales_cannot_create_purchase_order(client, sales_headers, purchaser_headers, db_session):
    """SALES 无 purchase:manage:建 PO 403。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so_id, so_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)
    r = await client.post("/api/v1/purchase-orders", headers=sales_headers, json={
        "source_sales_order_id": so_id, "supplier_id": sup["id"], "currency": "USD",
        "lines": [{"source_sales_order_line_id": so_lines[0]["id"], "qty": 1, "unit_price": 7}]})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_product_operator_cannot_read_purchase_orders(client, product_operator_headers):
    assert (await client.get("/api/v1/purchase-orders",
                             headers=product_operator_headers)).status_code == 403


@pytest.mark.asyncio
async def test_purchaser_can_read_and_create(client, purchaser_headers, sales_headers, db_session):
    """PURCHASER 全通:列表 200 + 建单 200 + 见真实采购价(有 read_cost)。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so_id, so_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)
    assert (await client.get("/api/v1/purchase-orders", headers=purchaser_headers)).status_code == 200
    r = await client.post("/api/v1/purchase-orders", headers=purchaser_headers, json={
        "source_sales_order_id": so_id, "supplier_id": sup["id"], "currency": "USD",
        "lines": [{"source_sales_order_line_id": so_lines[0]["id"], "qty": 2, "unit_price": 7}]})
    assert r.status_code == 200
    # 采购员有 read_cost:采购价/金额为真实值,不脱敏。
    assert float(r.json()["data"]["lines"][0]["unit_price"]) == 7
    assert float(r.json()["data"]["order"]["total_amount"]) == 14


@pytest.mark.asyncio
async def test_purchasable_lines_endpoint(client, purchaser_headers, sales_headers, db_session):
    """可采行接口:剩余额度 + 建议价(reference_price);建单前后 remaining 递减。"""
    cust, sku = await seed_catalog_and_customer(db_session, reference_price=6)
    so_id, so_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)

    pl = (await client.get(f"/api/v1/purchase-orders/purchasable-lines?source_sales_order_id={so_id}",
                           headers=purchaser_headers)).json()["data"]["items"]
    assert len(pl) == 1
    assert pl[0]["remaining_qty"] == 5 and pl[0]["default_unit_price"] == 6

    await client.post("/api/v1/purchase-orders", headers=purchaser_headers, json={
        "source_sales_order_id": so_id, "supplier_id": sup["id"], "currency": "USD",
        "lines": [{"source_sales_order_line_id": so_lines[0]["id"], "qty": 2, "unit_price": 6}]})
    pl2 = (await client.get(f"/api/v1/purchase-orders/purchasable-lines?source_sales_order_id={so_id}",
                            headers=purchaser_headers)).json()["data"]["items"]
    assert pl2[0]["remaining_qty"] == 3 and pl2[0]["covered_qty"] == 2


@pytest.mark.asyncio
async def test_purchasable_lines_requires_manage(client, sales_headers, purchaser_headers, db_session):
    """可采行接口守 purchase:manage:SALES 403。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so_id, _ = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    r = await client.get(
        f"/api/v1/purchase-orders/purchasable-lines?source_sales_order_id={so_id}",
        headers=sales_headers)
    assert r.status_code == 403


async def _strip_read_cost(db_session):
    """在本测试事务内摘掉 PURCHASER→purchase:read_cost 映射(SAVEPOINT 回滚,不污染其它测试)。
    权限每请求从 DB 加载(不嵌 JWT),故后续请求即视为「有 purchase:read 无 read_cost」——
    等价于入库步仓库角色,提前验红线端点级脱敏(无需提前造生产角色)。"""
    from sqlalchemy import select

    from app.db.models.permission import Permission
    from app.db.models.role import Role
    from app.db.models.role_permission import RolePermission
    role = (await db_session.execute(
        select(Role).where(Role.code == "PURCHASER"))).scalar_one()
    perm = (await db_session.execute(
        select(Permission).where(Permission.code == "purchase:read_cost"))).scalar_one()
    rp = (await db_session.execute(select(RolePermission).where(
        RolePermission.role_id == role.id,
        RolePermission.permission_id == perm.id))).scalar_one()
    await db_session.delete(rp)
    await db_session.flush()


@pytest.mark.asyncio
async def test_cost_redacted_on_all_three_surfaces_without_read_cost(
        client, purchaser_headers, sales_headers, db_session):
    """🔴红线端到端:无 purchase:read_cost 者在**列表 / 详情行 / SO 关联PO区**三处均拿到 null(后端脱敏)。
    数量非红线仍可见。验证 perms→can_see_cost→build 端点级接线,不止工厂单测。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so_id, so_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)
    r = await client.post("/api/v1/purchase-orders", headers=purchaser_headers, json={
        "source_sales_order_id": so_id, "supplier_id": sup["id"], "currency": "USD",
        "lines": [{"source_sales_order_line_id": so_lines[0]["id"], "qty": 2, "unit_price": 7}]})
    po_id = r.json()["data"]["order"]["id"]

    await _strip_read_cost(db_session)  # 此后 purchaser 视为无 read_cost

    # 1) 列表:total_amount 脱敏
    lst = (await client.get("/api/v1/purchase-orders", headers=purchaser_headers)).json()["data"]
    row = next(it for it in lst["items"] if it["id"] == po_id)
    assert row["total_amount"] is None

    # 2) 详情:头 total + 行 unit_price/line_total 脱敏,数量保留
    d = (await client.get(f"/api/v1/purchase-orders/{po_id}", headers=purchaser_headers)).json()["data"]
    assert d["order"]["total_amount"] is None
    assert d["lines"][0]["unit_price"] is None and d["lines"][0]["line_total"] is None
    assert float(d["lines"][0]["qty"]) == 2

    # 3) SO 关联PO区:related_purchase_orders 金额脱敏(仍下发,因还有 purchase:read)
    so = (await client.get(f"/api/v1/sales-orders/{so_id}", headers=purchaser_headers)).json()["data"]
    assert so["order"]["related_purchase_orders"][0]["total_amount"] is None
    assert so["order"]["related_purchase_orders"][0]["supplier_display"]  # 供应商身份仍在(有 purchase:read)
