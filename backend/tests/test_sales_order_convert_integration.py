"""转销售(主流程第2步):锁档报价 → 转销售单。convert 端点 + 销售单读端点 + 报价反查。"""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.category import Category
from app.db.models.customer import Customer
from app.db.models.sales_order import SalesOrder, SalesOrderLine
from app.db.models.sku import Sku
from app.db.models.spu import Spu


async def _seed_active(db):
    """建 ACTIVE catalog + 客户(报价选料要求可选货)。"""
    if not (await db.execute(select(Category).where(Category.code == "10"))).scalar_one_or_none():
        db.add(Category(code="10", parent_code=None, name_i18n={"zh": "钢材"},
                        level=1, is_leaf=True, sort_order=0))
        await db.flush()
    spu = Spu(spu_code="SPUA001", category_code="10", name_i18n={"zh": "工字钢"},
              created_by=1, status="ACTIVE")
    db.add(spu)
    await db.flush()
    sku = Sku(spu_id=spu.id, sku_code="SKUA001", unit="ton", name_i18n={"zh": "工字钢200"},
              created_by=1, status="ACTIVE")
    db.add(sku)
    cust = Customer(code="CA00001", name="客户A")
    db.add(cust)
    await db.commit()
    return cust, sku


async def _create_locked_quotation(client, headers, cust, sku):
    """建报价(2 行)并锁档,返回锁档态报价 id。"""
    r = await client.post("/api/v1/quotations", headers=headers, json={
        "customer_id": cust.id, "currency": "USD", "summary": "Q3 钢材",
        "lines": [{"sku_id": sku.id, "unit_price": 100, "qty": 2},
                  {"sku_id": sku.id, "unit_price": 50, "qty": 1}]})
    assert r.status_code == 200, r.text
    oid = r.json()["data"]["id"]
    lk = await client.post(f"/api/v1/quotations/{oid}/lock", headers=headers)
    assert lk.status_code == 200 and lk.json()["data"]["status"] == "LOCKED", lk.text
    return oid


@pytest.mark.asyncio
async def test_convert_locked_quotation_creates_sales_order(client, sales_headers, db_session):
    """核心:LOCKED 报价 → 转销售单原子创建 + 报价置 CONVERTED。"""
    cust, sku = await _seed_active(db_session)
    H = sales_headers
    oid = await _create_locked_quotation(client, H, cust, sku)

    r = await client.post(f"/api/v1/quotations/{oid}/convert", headers=H)
    assert r.status_code == 200, r.text
    detail = r.json()["data"]
    so = detail["order"]
    assert so["status"] == "CONFIRMED"
    assert so["source_quotation_id"] == oid
    assert so["no"].startswith("SO")
    assert float(so["total_amount"]) == 250
    assert len(detail["lines"]) == 2

    # 报价被驱动到终态 CONVERTED
    q = (await client.get(f"/api/v1/quotations/{oid}", headers=H)).json()["data"]
    assert q["order"]["status"] == "CONVERTED"


@pytest.mark.asyncio
async def test_convert_copies_line_snapshots(client, sales_headers, db_session):
    """行快照平移:销售单行忠实复制报价行(名/规格/单位/价/量/小计)+ 记来源报价行 id。"""
    cust, sku = await _seed_active(db_session)
    H = sales_headers
    oid = await _create_locked_quotation(client, H, cust, sku)
    ql = (await client.get(f"/api/v1/quotations/{oid}", headers=H)).json()["data"]["lines"]

    converted = (await client.post(f"/api/v1/quotations/{oid}/convert", headers=H)).json()["data"]
    so = converted["order"]
    detail = (await client.get(f"/api/v1/sales-orders/{so['id']}", headers=H)).json()["data"]
    sl = converted["lines"]
    assert len(sl) == len(ql) == 2
    for s, q in zip(sl, ql):
        assert s["name_snapshot"] == q["name_snapshot"]
        assert s["spec_text_snapshot"] == q["spec_text_snapshot"]
        assert s["unit_snapshot"] == q["unit_snapshot"]
        assert float(s["unit_price"]) == float(q["unit_price"])
        assert float(s["qty"]) == float(q["qty"])
        assert float(s["line_total"]) == float(q["line_total"])
        assert s["source_quotation_line_id"] == q["id"]
    assert converted["order"]["source_quotation_no"]  # convert 返回详情带来源报价号
    assert detail["order"]["source_quotation_no"]  # GET 详情带来源报价号


@pytest.mark.asyncio
async def test_sales_order_list_read(client, sales_headers, db_session):
    """销售单列表:转换后可在 /sales-orders 列表查到,带 display 名 + 行数。"""
    cust, sku = await _seed_active(db_session)
    H = sales_headers
    oid = await _create_locked_quotation(client, H, cust, sku)
    so = (await client.post(f"/api/v1/quotations/{oid}/convert", headers=H)).json()["data"]["order"]

    lst = (await client.get("/api/v1/sales-orders?status=CONFIRMED", headers=H)).json()["data"]
    assert lst["total"] >= 1
    row = next(it for it in lst["items"] if it["id"] == so["id"])
    assert row["customer_display"] == "客户A" and row["line_count"] == 2


@pytest.mark.asyncio
async def test_sales_order_list_filter_by_no(client, sales_headers, db_session):
    """列表按销售单号模糊搜:no= 参数只返回单号命中该片段的销售单。"""
    cust, sku = await _seed_active(db_session)
    H = sales_headers
    oid1 = await _create_locked_quotation(client, H, cust, sku)
    so1 = (await client.post(f"/api/v1/quotations/{oid1}/convert", headers=H)).json()["data"]["order"]
    oid2 = await _create_locked_quotation(client, H, cust, sku)
    so2 = (await client.post(f"/api/v1/quotations/{oid2}/convert", headers=H)).json()["data"]["order"]
    assert so1["no"] != so2["no"]

    lst = (await client.get(f"/api/v1/sales-orders?no={so1['no']}", headers=H)).json()["data"]
    ids = [it["id"] for it in lst["items"]]
    assert so1["id"] in ids
    assert so2["id"] not in ids


@pytest.mark.asyncio
async def test_convert_rejected_when_not_locked(client, sales_headers, db_session):
    """草稿(未锁档)报价不可转销售 → 41409。"""
    cust, sku = await _seed_active(db_session)
    H = sales_headers
    r = await client.post("/api/v1/quotations", headers=H, json={
        "customer_id": cust.id, "currency": "USD",
        "lines": [{"sku_id": sku.id, "unit_price": 10, "qty": 1}]})
    oid = r.json()["data"]["id"]  # DRAFT
    conv = await client.post(f"/api/v1/quotations/{oid}/convert", headers=H)
    assert conv.status_code == 409
    assert conv.json()["code"] == 41409


@pytest.mark.asyncio
async def test_reconvert_converted_quotation_rejected(client, sales_headers, db_session):
    """已转销售的报价(CONVERTED 终态)不可重复转 → 41409。"""
    cust, sku = await _seed_active(db_session)
    H = sales_headers
    oid = await _create_locked_quotation(client, H, cust, sku)
    assert (await client.post(f"/api/v1/quotations/{oid}/convert", headers=H)).status_code == 200
    again = await client.post(f"/api/v1/quotations/{oid}/convert", headers=H)
    assert again.status_code == 409 and again.json()["code"] == 41409


@pytest.mark.asyncio
async def test_quotation_detail_links_converted_sales_order(client, sales_headers, db_session):
    """报价详情反查出口:CONVERTED 报价的响应带 order.sales_order={id,no};未转时为 None。"""
    cust, sku = await _seed_active(db_session)
    H = sales_headers
    oid = await _create_locked_quotation(client, H, cust, sku)
    # 转换前:sales_order 为空
    q0 = (await client.get(f"/api/v1/quotations/{oid}", headers=H)).json()["data"]
    assert q0["order"].get("sales_order") is None

    so = (await client.post(f"/api/v1/quotations/{oid}/convert", headers=H)).json()["data"]["order"]
    q1 = (await client.get(f"/api/v1/quotations/{oid}", headers=H)).json()["data"]
    assert q1["order"]["sales_order"]["id"] == so["id"]
    assert q1["order"]["sales_order"]["no"] == so["no"]


@pytest.mark.asyncio
async def test_convert_requires_quote_manage(client, product_operator_headers, sales_headers,
                                             db_session):
    """convert 守 quote:manage:无此权限的角色(商品运营)禁止转销售 → 403。"""
    cust, sku = await _seed_active(db_session)
    oid = await _create_locked_quotation(client, sales_headers, cust, sku)
    r = await client.post(f"/api/v1/quotations/{oid}/convert", headers=product_operator_headers)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_sales_orders_read_requires_sales_read(client, product_operator_headers, db_session):
    """销售单读守 sales:read:无此权限的角色(商品运营)禁止查销售单 → 403。"""
    r = await client.get("/api/v1/sales-orders", headers=product_operator_headers)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_unique_source_quotation_blocks_second_sales_order(client, sales_headers, db_session):
    """DB 硬约束:UNIQUE(source_quotation_id) 挡「同一报价生成第二张销售单」(并发双转兜底)。"""
    cust, sku = await _seed_active(db_session)
    H = sales_headers
    oid = await _create_locked_quotation(client, H, cust, sku)
    await client.post(f"/api/v1/quotations/{oid}/convert", headers=H)

    dup = SalesOrder(
        no="SO260099", source_quotation_id=oid, customer_id=cust.id, salesperson_id=1,
        language="zh", currency="USD", status="CONFIRMED", total_amount=0, created_by=1)
    db_session.add(dup)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_unique_source_quotation_line_blocks_duplicate(client, sales_headers, db_session):
    """DB 硬约束:UNIQUE(source_quotation_line_id) 挡复制 bug 把同一报价行重复写入销售单。"""
    cust, sku = await _seed_active(db_session)
    H = sales_headers
    oid = await _create_locked_quotation(client, H, cust, sku)
    so = (await client.post(f"/api/v1/quotations/{oid}/convert", headers=H)).json()["data"]["order"]
    a_line = (await db_session.execute(
        select(SalesOrderLine).where(SalesOrderLine.sales_order_id == so["id"]))).scalars().first()

    dup = SalesOrderLine(
        sales_order_id=so["id"], sku_id=a_line.sku_id,
        source_quotation_line_id=a_line.source_quotation_line_id,  # 重复来源报价行
        name_snapshot="x", spec_text_snapshot="", unit_snapshot="", unit_price=1, qty=1,
        line_total=1, language="zh", sort_order=9)
    db_session.add(dup)
    with pytest.raises(IntegrityError):
        await db_session.flush()
