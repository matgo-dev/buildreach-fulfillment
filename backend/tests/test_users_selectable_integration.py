"""T10 报价人选择器:GET /users/selectable 只回 ACTIVE 且持 quote:manage 的 {id,name}。"""
import pytest


@pytest.mark.asyncio
async def test_selectable_returns_quote_managers_only(
    client, sales_headers, product_operator_headers
):
    # sales_headers 建了 SALES 用户(有 quote:manage);product_operator 无 quote:manage。
    r = await client.get("/api/v1/users/selectable", headers=sales_headers)
    assert r.status_code == 200, r.text
    items = r.json()["data"]
    names = {u["name"] for u in items}
    assert "销售" in names            # 持 quote:manage → 在列
    assert "商品运营" not in names     # 无 quote:manage → 不在列
    # 只回非敏感 id+name(选择器不下发邮箱/手机等)
    assert all(set(u.keys()) == {"id", "name"} for u in items)


@pytest.mark.asyncio
async def test_selectable_requires_quote_manage(client, product_operator_headers):
    # 无 quote:manage 的角色不能访问选择器
    r = await client.get("/api/v1/users/selectable", headers=product_operator_headers)
    assert r.status_code == 403
