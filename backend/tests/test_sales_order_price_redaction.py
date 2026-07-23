"""销售单客户售价红线脱敏回归测试。

🔴 客户售价(total_amount / unit_price / line_total)= 应收域(receivable:read)。
SALES 同时持 sales:read + receivable:read → 见真值;PURCHASER / LOGISTICS 持 sales:read
但不持 receivable:read → 后端置 null(列表 + 详情 + 转销售出口),排序不经成交额泄漏相对大小。

历史:该漏洞由整仓走查发现(PURCHASER/LOGISTICS 经 /sales-orders 拿到对客单价),
本用例由当时的探测脚本转正,防回归。
"""
import pytest
from tests.outbound_helpers import setup_available_stock

pytestmark = pytest.mark.asyncio

_PRICE_KEYS = ("unit_price", "line_total")


async def _detail(client, headers, so_id):
    r = await client.get(f"/api/v1/sales-orders/{so_id}", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    return data["order"], data["lines"]


async def test_redline_price_hidden_from_purchaser_and_logistics(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers)
    so_id = ctx["sales_order_id"]

    # 正例:SALES 持 receivable:read → 售价真值可见。
    order, lines = await _detail(client, sales_headers, so_id)
    assert order["total_amount"] is not None and order["total_amount"] > 0
    assert lines and all(ln["unit_price"] is not None for ln in lines)
    assert all(ln["line_total"] is not None for ln in lines)

    # 脱敏例:PURCHASER / LOGISTICS 无 receivable:read → 详情售价全 null。
    for headers in (purchaser_headers, logistics_headers):
        order, lines = await _detail(client, headers, so_id)
        assert order["total_amount"] is None
        assert lines
        for ln in lines:
            for k in _PRICE_KEYS:
                assert ln[k] is None, f"{k} 泄漏给无 receivable:read 角色"
        # 非红线字段仍在(数量/进度),证明是字段级脱敏而非整端点门控。
        assert all(ln["qty"] is not None for ln in lines)


async def test_redline_price_hidden_in_list_and_sort_not_leaked(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    await setup_available_stock(client, db_session, sales_headers, purchaser_headers)

    # 列表:SALES 见 total_amount,PURCHASER/LOGISTICS 为 null。
    r = await client.get("/api/v1/sales-orders", headers=sales_headers)
    assert any(it["total_amount"] is not None for it in r.json()["data"]["items"])

    for headers in (purchaser_headers, logistics_headers):
        r = await client.get("/api/v1/sales-orders", headers=headers)
        items = r.json()["data"]["items"]
        assert items
        assert all(it["total_amount"] is None for it in items)
        # 按成交额排序对无权者静默回落 created_at(不 500、不经排序泄漏大小),仍 200。
        r2 = await client.get(
            "/api/v1/sales-orders?sort=total_amount&dir=desc", headers=headers)
        assert r2.status_code == 200
        assert all(it["total_amount"] is None for it in r2.json()["data"]["items"])
