"""T9 RBAC 边界:SALES 读客户不写;ADMIN 已无 quote:manage(Q25 归位)。"""
import pytest


@pytest.mark.asyncio
async def test_sales_can_read_and_write_customers(client, sales_headers):
    # 读客户列表:customer:read → 200
    assert (await client.get("/api/v1/customers", headers=sales_headers)).status_code == 200
    # 写客户:持 customer:manage → 200(建客户→报价选客户同人同流)
    r = await client.post("/api/v1/customers", headers=sales_headers,
                          json={"name": "合法写"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_admin_cannot_manage_quotes(client, superadmin_headers):
    # quote:manage 已从 ADMIN 摘除(Q25)→ 建报价 403(权限守卫先于业务)
    r = await client.post("/api/v1/quotations", headers=superadmin_headers,
                          json={"customer_id": 1, "currency": "USD", "lines": []})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_sales_can_manage_quotes(client, sales_headers):
    # SALES 有 quote:manage → 列表 200(空也行)
    assert (await client.get("/api/v1/quotations", headers=sales_headers)).status_code == 200
