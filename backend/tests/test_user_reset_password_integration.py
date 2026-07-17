"""管理员重置密码:临时密码 + 强制首登改密 + token_version 踢旧会话 + 守卫负例。"""
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.models.user import User


async def _super_id(db) -> int:
    row = await db.execute(select(User).where(User.email == settings.SUPER_ADMIN_EMAIL))
    return row.scalar_one().id


async def _create_and_login(client, headers, *, email, password="Aa123456789"):
    r = await client.post("/api/v1/users", headers=headers, json={
        "email": email, "name": "被重置", "password": password, "role": "SALES",
        "must_change_password": False})
    assert r.status_code == 200, r.text
    u = r.json()["data"]
    lg = await client.post("/api/v1/auth/login",
                           json={"identifier": email, "password": password})
    assert lg.status_code == 200
    return u, {"Authorization": f"Bearer {lg.json()['data']['access_token']}"}


@pytest.mark.asyncio
async def test_reset_password_kicks_sessions_and_forces_change(client, superadmin_headers):
    u, old_headers = await _create_and_login(client, superadmin_headers,
                                             email="victim@fulfillment.local")
    assert (await client.get("/api/v1/auth/me", headers=old_headers)).status_code == 200

    rp = await client.post(f"/api/v1/users/{u['id']}/reset-password",
                           headers=superadmin_headers, json={"password": "Bb987654321"})
    assert rp.status_code == 200, rp.text
    assert rp.json()["data"]["must_change_password"] is True

    # 旧 token 一次失效(tv 不匹配)
    assert (await client.get("/api/v1/auth/me", headers=old_headers)).status_code == 401
    # 临时密码可登录;旧密码不再可用
    ok = await client.post("/api/v1/auth/login", json={
        "identifier": "victim@fulfillment.local", "password": "Bb987654321"})
    assert ok.status_code == 200
    bad = await client.post("/api/v1/auth/login", json={
        "identifier": "victim@fulfillment.local", "password": "Aa123456789"})
    assert bad.status_code in (400, 401)


@pytest.mark.asyncio
async def test_reset_password_guards(client, superadmin_headers, db_session):
    sa_id = await _super_id(db_session)
    # 不能重置自己(superadmin 重置 superadmin:先撞「自己」守卫)
    assert (await client.post(f"/api/v1/users/{sa_id}/reset-password",
                              headers=superadmin_headers,
                              json={"password": "Cc123456789"})).status_code == 400
    # 弱密码 422(schema 层)
    u, _ = await _create_and_login(client, superadmin_headers,
                                   email="weakreset@fulfillment.local")
    assert (await client.post(f"/api/v1/users/{u['id']}/reset-password",
                              headers=superadmin_headers,
                              json={"password": "123"})).status_code == 422


@pytest.mark.asyncio
async def test_reset_super_admin_blocked_via_other_admin(client, superadmin_headers, db_session):
    sa_id = await _super_id(db_session)
    r = await client.post("/api/v1/users", headers=superadmin_headers, json={
        "email": "admin3@fulfillment.local", "name": "管理员三号",
        "password": "Aa123456789", "role": "ADMIN", "must_change_password": False})
    assert r.status_code == 200
    lg = await client.post("/api/v1/auth/login", json={
        "identifier": "admin3@fulfillment.local", "password": "Aa123456789"})
    h3 = {"Authorization": f"Bearer {lg.json()['data']['access_token']}"}
    assert (await client.post(f"/api/v1/users/{sa_id}/reset-password",
                              headers=h3, json={"password": "Dd123456789"})).status_code == 400
