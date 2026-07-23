"""T8 报价 API:整单化端点(create/get/list/put/lock/unlock/void)+ 删旧 /lines。无整单硬删(退役走 void)。"""
import pytest
from sqlalchemy import select

from app.db.models.category import Category
from app.db.models.customer import Customer
from app.db.models.sku import Sku
from app.db.models.spu import Spu


async def _seed_active(db):
    """直接建 ACTIVE catalog + 客户(报价选料要求可选货)。"""
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


@pytest.mark.asyncio
async def test_quotation_full_lifecycle_api(client, sales_headers, db_session):
    cust, sku = await _seed_active(db_session)
    # 一 SKU 一价公理(§0-11):两行须不同 SKU,补建 sku2。
    sku2 = Sku(spu_id=sku.spu_id, sku_code="SKUA001B", unit="ton",
               name_i18n={"zh": "工字钢201"}, created_by=1, status="ACTIVE")
    db_session.add(sku2)
    await db_session.commit()
    H = sales_headers

    # create(整单:表头 + 2 行,不同 SKU)
    r = await client.post("/api/v1/quotations", headers=H, json={
        "customer_id": cust.id, "currency": "USD", "summary": "Q3 钢材",
        "lines": [{"sku_id": sku.id, "unit_price": 100, "qty": 2},
                  {"sku_id": sku2.id, "unit_price": 50, "qty": 1}]})
    assert r.status_code == 200, r.text
    order = r.json()["data"]
    oid = order["id"]
    assert str(order["total_amount"]) in ("250.00", "250.0") or float(order["total_amount"]) == 250
    assert order["salesperson_id"] and order["summary"] == "Q3 钢材"  # 报价人默认=建单销售

    # get
    g = (await client.get(f"/api/v1/quotations/{oid}", headers=H)).json()["data"]
    assert len(g["lines"]) == 2
    updated_at = g["order"]["updated_at"]

    # list
    lst = (await client.get("/api/v1/quotations?status=DRAFT", headers=H)).json()["data"]
    assert lst["total"] >= 1 and any(it["id"] == oid for it in lst["items"])

    # put(删一行 + 改一行,带乐观锁)
    line_ids = [ln["id"] for ln in g["lines"]]
    p = await client.put(f"/api/v1/quotations/{oid}", headers=H, json={
        "customer_id": cust.id, "currency": "USD", "expected_updated_at": updated_at,
        "lines": [{"id": line_ids[0], "sku_id": sku.id, "unit_price": 100, "qty": 3}]})
    assert p.status_code == 200, p.text
    assert float(p.json()["data"]["total_amount"]) == 300

    # 旧 /lines 端点已删
    old = await client.post(f"/api/v1/quotations/{oid}/lines", headers=H,
                            json={"sku_id": sku.id, "unit_price": 1, "qty": 1})
    assert old.status_code in (404, 405)

    # lock → unlock → void
    assert (await client.post(f"/api/v1/quotations/{oid}/lock", headers=H)
            ).json()["data"]["status"] == "LOCKED"
    assert (await client.post(f"/api/v1/quotations/{oid}/unlock", headers=H)
            ).json()["data"]["status"] == "DRAFT"
    assert (await client.post(f"/api/v1/quotations/{oid}/void", headers=H,
                              json={"reason": "取消"})).json()["data"]["status"] == "VOID"


@pytest.mark.asyncio
async def test_create_language_defaults_from_customer(client, sales_headers, db_session):
    _, sku = await _seed_active(db_session)
    cust = Customer(code="CA00002", name="斯语客户", quote_language="sw")
    db_session.add(cust)
    await db_session.commit()
    r = await client.post("/api/v1/quotations", headers=sales_headers, json={
        "customer_id": cust.id, "currency": "USD",
        "lines": [{"sku_id": sku.id, "unit_price": 10, "qty": 1}]})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["language"] == "sw"   # 报价单继承客户报价语言


@pytest.mark.asyncio
async def test_snapshot_is_server_authoritative(client, sales_headers, db_session):
    """契约:行快照由服务端从 SKU 权威冻结,客户端传入的 _snapshot 值一律不采信。
    否则销售可把规格/名称写成与真实 SKU 矛盾的文本,冻结快照不再忠实反映选料。"""
    cust, sku = await _seed_active(db_session)  # SKU 名=工字钢200,单位=ton→吨,无 spec
    r = await client.post("/api/v1/quotations", headers=sales_headers, json={
        "customer_id": cust.id, "currency": "USD",
        "lines": [{
            "sku_id": sku.id, "unit_price": 10, "qty": 1,
            "name_snapshot": "伪造名称",
            "spec_text_snapshot": "伪造规格",
            "unit_snapshot": "伪造单位",
        }]})
    assert r.status_code == 200, r.text
    oid = r.json()["data"]["id"]
    line = (await client.get(f"/api/v1/quotations/{oid}", headers=sales_headers)
            ).json()["data"]["lines"][0]
    assert line["name_snapshot"] == "工字钢200"    # 服务端 SKU 名,非客户端伪造
    assert line["unit_snapshot"] == "吨"           # 服务端冻 SKU 的 units.code(ton),展示层翻译
    assert "伪造" not in line["spec_text_snapshot"]  # 规格服务端组合,不含客户端注入


@pytest.mark.asyncio
async def test_snapshot_frozen_at_pick_survives_master_change(client, sales_headers, db_session):
    """契约(freeze-at-pick):快照在"商品被选进行"时冻结;此后同一 SKU 改数量/价/备注
    不重算,主数据(名/规格/单位)变更也不回写已在行上的定格值 —— 对齐 Odoo/SAP/NetSuite。
    理由:行的单价/数量是相对定格那刻的规格/单位才有意义,retroactive 改会静默失真。"""
    cust, sku = await _seed_active(db_session)  # name=工字钢200
    H = sales_headers
    r = await client.post("/api/v1/quotations", headers=H, json={
        "customer_id": cust.id, "currency": "USD",
        "lines": [{"sku_id": sku.id, "unit_price": 10, "qty": 1}]})
    oid = r.json()["data"]["id"]
    g = (await client.get(f"/api/v1/quotations/{oid}", headers=H)).json()["data"]
    lid = g["lines"][0]["id"]
    assert g["lines"][0]["name_snapshot"] == "工字钢200"
    updated_at = g["order"]["updated_at"]

    # 商品主数据被改(改名),SKU 仍 ACTIVE
    sku.name_i18n = {"zh": "工字钢200-改名后"}
    db_session.add(sku)
    await db_session.commit()

    # 只改数量存草稿(同 sku_id)→ 快照不应刷新
    p = await client.put(f"/api/v1/quotations/{oid}", headers=H, json={
        "customer_id": cust.id, "currency": "USD", "expected_updated_at": updated_at,
        "lines": [{"id": lid, "sku_id": sku.id, "unit_price": 10, "qty": 5}]})
    assert p.status_code == 200, p.text
    g2 = (await client.get(f"/api/v1/quotations/{oid}", headers=H)).json()["data"]
    assert float(g2["lines"][0]["qty"]) == 5
    assert g2["lines"][0]["name_snapshot"] == "工字钢200"  # 定格未变,不随主数据漂移


@pytest.mark.asyncio
async def test_snapshot_refreshes_when_line_sku_changes(client, sales_headers, db_session):
    """契约:同一行**换了商品**(sku_id 变)→ 快照按新 SKU 重新冻结。"""
    cust, sku = await _seed_active(db_session)  # name=工字钢200
    sku2 = Sku(spu_id=sku.spu_id, sku_code="SKUA002", unit="ton",
               name_i18n={"zh": "工字钢300"}, created_by=1, status="ACTIVE")
    db_session.add(sku2)
    await db_session.commit()
    H = sales_headers
    r = await client.post("/api/v1/quotations", headers=H, json={
        "customer_id": cust.id, "currency": "USD",
        "lines": [{"sku_id": sku.id, "unit_price": 10, "qty": 1}]})
    oid = r.json()["data"]["id"]
    g = (await client.get(f"/api/v1/quotations/{oid}", headers=H)).json()["data"]
    lid, updated_at = g["lines"][0]["id"], g["order"]["updated_at"]
    assert g["lines"][0]["name_snapshot"] == "工字钢200"

    # 把该行换成 sku2
    p = await client.put(f"/api/v1/quotations/{oid}", headers=H, json={
        "customer_id": cust.id, "currency": "USD", "expected_updated_at": updated_at,
        "lines": [{"id": lid, "sku_id": sku2.id, "unit_price": 10, "qty": 1}]})
    assert p.status_code == 200, p.text
    g2 = (await client.get(f"/api/v1/quotations/{oid}", headers=H)).json()["data"]
    assert g2["lines"][0]["name_snapshot"] == "工字钢300"  # 换商品→按新 SKU 刷新
