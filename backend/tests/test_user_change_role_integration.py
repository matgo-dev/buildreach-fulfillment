"""改角色:即时生效(权限每请求查库,不踢会话)+ 守卫负例 + 幂等。"""
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.models.user import User


async def _super_id(db) -> int:
    row = await db.execute(select(User).where(User.email == settings.SUPER_ADMIN_EMAIL))
    return row.scalar_one().id


async def _create_and_login(client, headers, *, email, role="SALES"):
    r = await client.post("/api/v1/users", headers=headers, json={
        "email": email, "name": "换角色", "password": "Aa123456789", "role": role,
        "must_change_password": False})
    assert r.status_code == 200, r.text
    u = r.json()["data"]
    lg = await client.post("/api/v1/auth/login",
                           json={"identifier": email, "password": "Aa123456789"})
    return u, {"Authorization": f"Bearer {lg.json()['data']['access_token']}"}


@pytest.mark.asyncio
async def test_change_role_takes_effect_immediately(client, superadmin_headers):
    """SALES→PRODUCT_OPERATOR:同一个 token,客户列表 200→403(每请求查库,无需踢会话)。"""
    u, h = await _create_and_login(client, superadmin_headers,
                                   email="rolechg@fulfillment.local")
    assert (await client.get("/api/v1/customers", headers=h)).status_code == 200

    r = await client.put(f"/api/v1/users/{u['id']}/role", headers=superadmin_headers,
                         json={"role": "PRODUCT_OPERATOR"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["roles"] == ["PRODUCT_OPERATOR"]

    assert (await client.get("/api/v1/customers", headers=h)).status_code == 403


@pytest.mark.asyncio
async def test_change_role_guards(client, superadmin_headers, db_session):
    sa_id = await _super_id(db_session)
    u, _ = await _create_and_login(client, superadmin_headers,
                                   email="roleguard@fulfillment.local")
    # 非法角色(白名单外)
    assert (await client.put(f"/api/v1/users/{u['id']}/role", headers=superadmin_headers,
                             json={"role": "BUYER"})).status_code == 400
    # 不能改自己(superadmin 改 superadmin:先撞「自己」守卫)
    assert (await client.put(f"/api/v1/users/{sa_id}/role", headers=superadmin_headers,
                             json={"role": "SALES"})).status_code == 400
    # 不能改 super admin(管理员四号操作)
    r = await client.post("/api/v1/users", headers=superadmin_headers, json={
        "email": "admin4@fulfillment.local", "name": "管理员四号",
        "password": "Aa123456789", "role": "ADMIN", "must_change_password": False})
    assert r.status_code == 200
    lg = await client.post("/api/v1/auth/login", json={
        "identifier": "admin4@fulfillment.local", "password": "Aa123456789"})
    h4 = {"Authorization": f"Bearer {lg.json()['data']['access_token']}"}
    assert (await client.put(f"/api/v1/users/{sa_id}/role", headers=h4,
                             json={"role": "SALES"})).status_code == 400


@pytest.mark.asyncio
async def test_change_role_last_admin_guard_service_level(db_session, superadmin_headers, monkeypatch):
    """守卫纵深:super 保护解除后,唯一 ACTIVE ADMIN 不能被改走角色(镜像停用守卫)。"""
    from app.core.exceptions import ValidationFailedError
    from app.services.user_service import change_role

    sa_id = await _super_id(db_session)
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAIL", "nobody@nowhere.local")
    with pytest.raises(ValidationFailedError):
        await change_role(db_session, target_user_id=sa_id, new_role="SALES",
                          actor_user_id=0, actor_user_email="t@t")


@pytest.mark.asyncio
async def test_change_role_idempotent(client, superadmin_headers):
    u, _ = await _create_and_login(client, superadmin_headers,
                                   email="roleidem@fulfillment.local")
    r = await client.put(f"/api/v1/users/{u['id']}/role", headers=superadmin_headers,
                         json={"role": "SALES"})
    assert r.status_code == 200 and r.json()["data"]["roles"] == ["SALES"]
