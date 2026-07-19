"""契约:单据行 `unit_snapshot` **存 units.code**,展示层按内部界面语言(zh)翻译。

旧口径按**报价语言**冻结展示文字(en 单存 "pc"、zh 单存 "件"),中文运营界面因此单位列
中英混排。现在冻结 code、展示时翻译,故英文单在内部界面上单位也显示中文。

单位取 `piece` 而非 bag:piece 的 code / en 标签 / zh 标签三者两两不同
(`piece` / `pc` / `件`),旧口径与新口径在**列值和响应值两侧都有区分力**;bag 的 en 标签
恰好与 code 同形("bag"),列侧断言分不出新旧,鉴别力弱。

本测试走完整链路 报价→销售单→采购单→入库单,每一环同时钉两侧:
- API 详情返回中文标签("件");
- 数据库列里存的是 code("piece")—— 防有人"顺手"把翻译结果写回 ORM(autoflush 会落库)。
"""
import pytest
from sqlalchemy import text

from tests.inventory_helpers import (
    create_supplier,
    make_confirmed_po,
    make_confirmed_so,
    receive_inbound,
    seed_inventory_catalog,
)

_CODE = "piece"    # units.code
_LABEL = "件"      # units.label_i18n.zh(内部界面语言 = zh)
_EN_LABEL = "pc"   # units.label_i18n.en —— 旧口径下英文单冻的就是它


async def _column_values(db, table: str) -> set[str]:
    return set((await db.execute(text(f"SELECT unit_snapshot FROM {table}"))).scalars().all())


@pytest.mark.asyncio
async def test_unit_snapshot_stores_code_and_renders_zh_for_en_order(
        client, db_session, sales_headers, purchaser_headers):
    # 英文报价语言的客户 + 单位 piece 的 SKU:旧口径会把 "pc" 冻进 4 张行表。
    cust, skus = await seed_inventory_catalog(
        db_session, sku_codes=("SKUUNIT_A",), unit=_CODE,
        cust_code="CUNIT001", quote_language="en")
    sku = skus[0]

    # ① 报价 → 销售单(make_confirmed_so 内含 报价→锁档→转销售)
    so_id, so_lines = await make_confirmed_so(
        client, sales_headers, cust, [{"sku_id": sku.id, "unit_price": 10, "qty": 6}])
    assert so_lines[0]["unit_snapshot"] == _LABEL          # 转销售响应即已翻译
    assert await _column_values(db_session, "quotation_lines") == {_CODE}
    assert await _column_values(db_session, "sales_order_lines") == {_CODE}

    so_detail = (await client.get(f"/api/v1/sales-orders/{so_id}",
                                  headers=sales_headers)).json()["data"]
    assert so_detail["order"]["language"] == "en"          # 单据语言仍是 en(对客户输出不受影响)
    assert so_detail["lines"][0]["unit_snapshot"] == _LABEL

    qid = so_detail["order"]["source_quotation_id"]
    q_detail = (await client.get(f"/api/v1/quotations/{qid}",
                                 headers=sales_headers)).json()["data"]
    assert q_detail["lines"][0]["unit_snapshot"] == _LABEL

    # ② 采购单(内部拷贝链传 code,不经翻译)
    supplier = await create_supplier(client, purchaser_headers)
    po_id, po_lines = await make_confirmed_po(
        client, purchaser_headers, source_sales_order_id=so_id, so_lines=so_lines,
        supplier=supplier,
        lines=[{"source_sales_order_line_id": so_lines[0]["id"], "qty": 6, "unit_price": "4.00"}])
    assert po_lines[0]["unit_snapshot"] == _LABEL
    assert await _column_values(db_session, "purchase_order_lines") == {_CODE}

    # ③ 入库单
    inb_id = await receive_inbound(
        client, purchaser_headers, purchase_order_id=po_id,
        lines=[{"purchase_order_line_id": po_lines[0]["id"], "qty": 6}])
    inb_detail = (await client.get(f"/api/v1/inbound-orders/{inb_id}",
                                   headers=purchaser_headers)).json()["data"]
    assert inb_detail["lines"][0]["unit_snapshot"] == _LABEL
    assert await _column_values(db_session, "inbound_order_lines") == {_CODE}

    # ④ 建单器数据源(可采行 / 可收行)同样走展示层翻译
    purchasable = (await client.get(
        "/api/v1/purchase-orders/purchasable-lines",
        params={"source_sales_order_id": so_id}, headers=purchaser_headers)).json()["data"]["items"]
    assert purchasable[0]["unit_snapshot"] == _LABEL
    receivable = (await client.get(
        "/api/v1/inbound-orders/receivable-lines",
        params={"purchase_order_id": po_id}, headers=purchaser_headers)).json()["data"]["items"]
    assert receivable[0]["unit_snapshot"] == _LABEL

    # 兜底:旧口径的英文展示值绝不该再出现在任何一列 / 任何响应里。
    for table in ("quotation_lines", "sales_order_lines",
                  "purchase_order_lines", "inbound_order_lines"):
        assert _EN_LABEL not in await _column_values(db_session, table)
