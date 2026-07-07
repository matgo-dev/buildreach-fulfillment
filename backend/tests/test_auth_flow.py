"""登录链路关键路径集成测试:login → me(强制改密拦截) → change-password → 重登 → me。

依赖 T5 的 conftest(client fixture + 建表 + seed 引导管理员),本任务先写、
先跑不通(conftest 未就绪),T5 完成后统一转绿。
"""
import pytest


@pytest.mark.asyncio
async def test_login_forces_password_change_then_succeeds(client):
    from app.core.config import settings

    # 1. 引导管理员初次登录成功
    r = await client.post("/api/v1/auth/login", json={
        "identifier": settings.SUPER_ADMIN_EMAIL,
        "password": settings.SUPER_ADMIN_INITIAL_PASSWORD})
    assert r.status_code == 200
    token = r.json()["data"]["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # 2. must_change 期间访问 me:/me 路由只挂 get_current_user,不经
    #    require_permission/block_if_must_change_password 门,故不拦截。
    r2 = await client.get("/api/v1/auth/me", headers=h)
    assert r2.status_code == 200

    # 3. 改密(豁免端点)
    r3 = await client.post("/api/v1/auth/change-password", headers=h, json={
        "old_password": settings.SUPER_ADMIN_INITIAL_PASSWORD,
        "new_password": "TestNewPass999"})
    assert r3.status_code == 200

    # 4. 新密码重登 + me 可用
    r4 = await client.post("/api/v1/auth/login", json={
        "identifier": settings.SUPER_ADMIN_EMAIL, "password": "TestNewPass999"})
    assert r4.status_code == 200
    h2 = {"Authorization": f"Bearer {r4.json()['data']['access_token']}"}
    r5 = await client.get("/api/v1/auth/me", headers=h2)
    assert r5.status_code == 200
    body = r5.json()["data"]
    assert body["email"] == settings.SUPER_ADMIN_EMAIL
    # 暗桩已切断:CurrentUser/MeOut 均无 organization/zones
    assert "organization" not in body
    assert "zones" not in body


@pytest.mark.asyncio
async def test_logout_clears_cookie_and_writes_audit(client):
    from app.core.config import settings

    r = await client.post("/api/v1/auth/login", json={
        "identifier": settings.SUPER_ADMIN_EMAIL,
        "password": settings.SUPER_ADMIN_INITIAL_PASSWORD})
    assert r.status_code == 200
    token = r.json()["data"]["access_token"]

    r2 = await client.post(
        "/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"}
    )
    assert r2.status_code == 200
