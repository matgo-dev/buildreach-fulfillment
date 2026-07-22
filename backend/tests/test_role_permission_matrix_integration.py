"""角色权限矩阵只读查询:GET /api/v1/roles。role:manage 守卫(当前仅 ADMIN 持有)。"""
import pytest


@pytest.mark.asyncio
async def test_list_roles_returns_full_matrix(client, superadmin_headers):
    r = await client.get("/api/v1/roles", headers=superadmin_headers)
    assert r.status_code == 200, r.text
    items = r.json()["data"]
    codes = {it["code"] for it in items}
    assert codes == {"ADMIN", "PRODUCT_OPERATOR", "SALES", "PURCHASER", "LOGISTICS", "FINANCE"}

    admin = next(it for it in items if it["code"] == "ADMIN")
    admin_codes = {p["code"] for p in admin["permissions"]}
    assert {"user:manage", "role:manage", "permission:manage"} <= admin_codes
    assert "quote:manage" not in admin_codes  # Q25:ADMIN 不触业务写权限

    sales = next(it for it in items if it["code"] == "SALES")
    sales_codes = {p["code"] for p in sales["permissions"]}
    assert "quote:manage" in sales_codes
    assert "user:manage" not in sales_codes

    # 每个权限点带 name/module,供前端直接渲染,不需另查常量表
    sample = admin["permissions"][0]
    assert set(sample.keys()) == {"code", "name", "module"}


@pytest.mark.asyncio
async def test_list_roles_requires_role_manage(client, sales_headers, purchaser_headers):
    r = await client.get("/api/v1/roles", headers=sales_headers)
    assert r.status_code == 403

    r2 = await client.get("/api/v1/roles", headers=purchaser_headers)
    assert r2.status_code == 403
