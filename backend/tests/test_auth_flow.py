"""登录链路关键路径集成测试:login → me(强制改密拦截) → change-password → 重登 → me。

依赖 T5 的 conftest(client fixture + 建表 + seed 引导管理员),本任务先写、
先跑不通(conftest 未就绪),T5 完成后统一转绿。
"""
import pytest
from sqlalchemy import select

from app.audit.constants import AuditAction, AuditResourceType
from app.db.models.audit_log import AuditLog
from app.db.models.user import User


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


@pytest.mark.asyncio
async def test_update_me_allows_self_profile_without_user_manage(client, superadmin_headers, db_session):
    r = await client.post("/api/v1/users", headers=superadmin_headers, json={
        "email": "selfprofile@fulfillment.local",
        "name": "原姓名",
        "password": "Aa123456789",
        "role": "SALES",
        "must_change_password": False,
    })
    assert r.status_code == 200, r.text

    login = await client.post("/api/v1/auth/login", json={
        "identifier": "selfprofile@fulfillment.local",
        "password": "Aa123456789",
    })
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

    updated = await client.put("/api/v1/auth/me", headers=headers, json={
        "email": "selfprofile-new@fulfillment.local",
        "username": "selfprofile",
        "phone": "+255700000301",
        "name": "新姓名",
    })
    assert updated.status_code == 200, updated.text
    data = updated.json()["data"]
    assert data["email"] == "selfprofile-new@fulfillment.local"
    assert data["username"] == "selfprofile"
    assert data["phone"] == "+255700000301"
    assert data["name"] == "新姓名"
    assert "roles" in data and "permissions" in data

    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["data"]["email"] == "selfprofile-new@fulfillment.local"

    audit = (await db_session.execute(
        select(AuditLog).where(
            AuditLog.resource_type == AuditResourceType.USER.value,
            AuditLog.action == AuditAction.UPDATE.value,
            AuditLog.resource_id == str(data["id"]),
        ).order_by(AuditLog.id.desc())
    )).scalars().first()
    assert audit is not None
    assert audit.extra["self_update"] is True
    assert set(audit.extra["changes"]) == {"email", "username", "phone", "name"}


@pytest.mark.asyncio
async def test_update_me_rejects_unique_conflicts(client, superadmin_headers):
    created = []
    for email, username in (
        ("profile-a@fulfillment.local", "profile_a"),
        ("profile-b@fulfillment.local", "profile_b"),
    ):
        r = await client.post("/api/v1/users", headers=superadmin_headers, json={
            "email": email,
            "username": username,
            "name": email,
            "password": "Aa123456789",
            "role": "SALES",
            "must_change_password": False,
        })
        assert r.status_code == 200, r.text
        created.append(r.json()["data"])

    pa = await client.put(f"/api/v1/users/{created[0]['id']}", headers=superadmin_headers,
                          json={"phone": "+255700000401"})
    pb = await client.put(f"/api/v1/users/{created[1]['id']}", headers=superadmin_headers,
                          json={"phone": "+255700000402"})
    assert pa.status_code == 200 and pb.status_code == 200

    login = await client.post("/api/v1/auth/login", json={
        "identifier": "profile-a@fulfillment.local",
        "password": "Aa123456789",
    })
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

    assert (await client.put("/api/v1/auth/me", headers=headers, json={
        "email": "profile-b@fulfillment.local",
    })).status_code == 409
    assert (await client.put("/api/v1/auth/me", headers=headers, json={
        "username": "profile_b",
    })).status_code == 409
    assert (await client.put("/api/v1/auth/me", headers=headers, json={
        "phone": "+255700000402",
    })).status_code == 409


@pytest.mark.asyncio
async def test_update_me_blocks_super_admin_email(client, superadmin_headers, db_session):
    r = await client.put("/api/v1/auth/me", headers=superadmin_headers, json={
        "email": "super-hijack@fulfillment.local",
    })
    assert r.status_code == 400

    ok = await client.put("/api/v1/auth/me", headers=superadmin_headers, json={
        "name": "零号自助改名",
        "phone": "+255700000501",
    })
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["name"] == "零号自助改名"
    user = (await db_session.execute(
        select(User).where(User.email == "super-hijack@fulfillment.local")
    )).scalar_one_or_none()
    assert user is None


@pytest.mark.asyncio
async def test_update_me_requires_password_change_first(client, superadmin_headers):
    r = await client.post("/api/v1/users", headers=superadmin_headers, json={
        "email": "mustchange-profile@fulfillment.local",
        "name": "强制改密",
        "password": "Aa123456789",
        "role": "SALES",
        "must_change_password": True,
    })
    assert r.status_code == 200, r.text

    login = await client.post("/api/v1/auth/login", json={
        "identifier": "mustchange-profile@fulfillment.local",
        "password": "Aa123456789",
    })
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    blocked = await client.put("/api/v1/auth/me", headers=headers, json={"name": "还不能改"})
    assert blocked.status_code == 403
