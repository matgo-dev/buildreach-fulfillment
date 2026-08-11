"""改角色:即时生效(权限每请求查库,不踢会话)+ 守卫负例 + 幂等。"""
import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

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
async def test_change_roles_take_effect_immediately(client, superadmin_headers):
    """SALES→PRODUCT_OPERATOR+PURCHASER:同一个 token,客户列表 200→403。"""
    u, h = await _create_and_login(client, superadmin_headers,
                                   email="rolechg@fulfillment.local")
    assert (await client.get("/api/v1/customers", headers=h)).status_code == 200

    r = await client.put(f"/api/v1/users/{u['id']}/roles", headers=superadmin_headers,
                         json={"roles": ["PRODUCT_OPERATOR", "PURCHASER"]})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["roles"] == ["PRODUCT_OPERATOR", "PURCHASER"]

    assert (await client.get("/api/v1/customers", headers=h)).status_code == 403


@pytest.mark.asyncio
async def test_custom_role_can_be_assigned_and_takes_effect(client, superadmin_headers):
    role = await client.post("/api/v1/roles", headers=superadmin_headers, json={
        "code": "PRODUCT_VIEWER",
        "name": "商品只读",
        "permissions": ["product:read"],
    })
    assert role.status_code == 200, role.text
    u, h = await _create_and_login(client, superadmin_headers,
                                   email="custom-role@fulfillment.local", role="SALES")
    assert (await client.get("/api/v1/customers", headers=h)).status_code == 200

    r = await client.put(f"/api/v1/users/{u['id']}/roles", headers=superadmin_headers,
                         json={"roles": ["PRODUCT_VIEWER"]})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["roles"] == ["PRODUCT_VIEWER"]

    assert (await client.get("/api/v1/customers", headers=h)).status_code == 403
    assert (await client.get("/api/v1/spus", headers=h)).status_code == 200


@pytest.mark.asyncio
async def test_change_role_guards(client, superadmin_headers, db_session):
    sa_id = await _super_id(db_session)
    u, _ = await _create_and_login(client, superadmin_headers,
                                   email="roleguard@fulfillment.local")
    # 非法角色(白名单外)
    assert (await client.put(f"/api/v1/users/{u['id']}/roles", headers=superadmin_headers,
                             json={"roles": ["BUYER"]})).status_code == 400
    # 空角色集合
    assert (await client.put(f"/api/v1/users/{u['id']}/roles", headers=superadmin_headers,
                             json={"roles": []})).status_code == 422
    # 不能改自己(superadmin 改 superadmin:先撞「自己」守卫)
    assert (await client.put(f"/api/v1/users/{sa_id}/roles", headers=superadmin_headers,
                             json={"roles": ["SALES"]})).status_code == 400
    # 不能改 super admin(管理员四号操作)
    r = await client.post("/api/v1/users", headers=superadmin_headers, json={
        "email": "admin4@fulfillment.local", "name": "管理员四号",
        "password": "Aa123456789", "role": "ADMIN", "must_change_password": False})
    assert r.status_code == 200
    lg = await client.post("/api/v1/auth/login", json={
        "identifier": "admin4@fulfillment.local", "password": "Aa123456789"})
    h4 = {"Authorization": f"Bearer {lg.json()['data']['access_token']}"}
    assert (await client.put(f"/api/v1/users/{sa_id}/roles", headers=h4,
                             json={"roles": ["SALES"]})).status_code == 400


@pytest.mark.asyncio
async def test_change_role_last_admin_guard_service_level(db_session, superadmin_headers, monkeypatch):
    """守卫纵深:super 保护解除后,唯一 ACTIVE ADMIN 不能被改走角色(镜像停用守卫)。"""
    from app.core.exceptions import ValidationFailedError
    from app.services.user_service import change_roles

    sa_id = await _super_id(db_session)
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAIL", "nobody@nowhere.local")
    with pytest.raises(ValidationFailedError):
        await change_roles(db_session, target_user_id=sa_id, new_roles=["SALES"],
                           actor_user_id=0, actor_user_email="t@t")


@pytest.mark.asyncio
async def test_change_roles_idempotent(client, superadmin_headers):
    u, _ = await _create_and_login(client, superadmin_headers,
                                   email="roleidem@fulfillment.local")
    r = await client.put(f"/api/v1/users/{u['id']}/roles", headers=superadmin_headers,
                         json={"roles": ["SALES"]})
    assert r.status_code == 200 and r.json()["data"]["roles"] == ["SALES"]


@pytest.mark.asyncio
async def test_legacy_change_role_endpoint_still_works(client, superadmin_headers):
    u, _ = await _create_and_login(client, superadmin_headers,
                                   email="rolelegacy@fulfillment.local")
    r = await client.put(f"/api/v1/users/{u['id']}/role", headers=superadmin_headers,
                         json={"role": "PRODUCT_OPERATOR"})
    assert r.status_code == 200 and r.json()["data"]["roles"] == ["PRODUCT_OPERATOR"]


@pytest.mark.asyncio
async def test_concurrent_role_replacements_do_not_merge_roles(_engine, monkeypatch):
    """两个独立事务同时替换同一用户角色时,最终集合必须等于某一个请求目标。"""
    from app.services import user_service

    Session = async_sessionmaker(_engine, expire_on_commit=False)
    email = f"role-race-{uuid4().hex}@fulfillment.local"
    original_get_user_roles = user_service.get_user_roles
    target_id: int | None = None
    both_read_old_roles = asyncio.Event()
    old_role_reads = 0

    async with Session() as setup_db:
        target = await user_service.create_internal_user(
            setup_db,
            email=email,
            name="并发改角色",
            password="Aa123456789",
            role="SALES",
            must_change_password=False,
            actor_user_id=0,
            actor_user_email="system@test",
        )
        target_id = target.id

    async def coordinated_get_user_roles(db, user_id: int) -> list[str]:
        nonlocal old_role_reads
        roles = await original_get_user_roles(db, user_id)
        if user_id == target_id and roles == ["SALES"]:
            old_role_reads += 1
            if old_role_reads == 2:
                both_read_old_roles.set()
            try:
                await asyncio.wait_for(both_read_old_roles.wait(), timeout=0.2)
            except asyncio.TimeoutError:
                pass
        return roles

    monkeypatch.setattr(user_service, "get_user_roles", coordinated_get_user_roles)

    async def replace_with(role_code: str) -> None:
        assert target_id is not None
        async with Session() as db:
            await user_service.change_roles(
                db,
                target_user_id=target_id,
                new_roles=[role_code],
                actor_user_id=0,
                actor_user_email="system@test",
            )

    try:
        await asyncio.gather(replace_with("PURCHASER"), replace_with("FINANCE"))

        assert target_id is not None
        async with Session() as verify_db:
            final_roles = await original_get_user_roles(verify_db, target_id)
        assert final_roles in (["PURCHASER"], ["FINANCE"])
    finally:
        if target_id is not None:
            async with Session() as cleanup_db:
                await cleanup_db.execute(delete(User).where(User.id == target_id))
                await cleanup_db.commit()
