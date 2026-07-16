"""用户管理 API(T20 接线):建号/列表筛选/编辑/启停守卫 + RBAC 门禁。"""
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.models.user import User


async def _super_id(db) -> int:
    row = await db.execute(select(User).where(User.email == settings.SUPER_ADMIN_EMAIL))
    return row.scalar_one().id


async def _create(client, headers, *, email, name="测试号", role="SALES",
                  password="Aa123456789", must_change=True):
    r = await client.post("/api/v1/users", headers=headers, json={
        "email": email, "name": name, "password": password, "role": role,
        "must_change_password": must_change})
    assert r.status_code == 200, r.text
    return r.json()["data"]


@pytest.mark.asyncio
async def test_create_and_list_user(client, superadmin_headers):
    u = await _create(client, superadmin_headers, email="op1@fulfillment.local",
                      name="运营一号", role="PRODUCT_OPERATOR")
    assert u["roles"] == ["PRODUCT_OPERATOR"] and u["must_change_password"] is True

    lst = (await client.get("/api/v1/users", headers=superadmin_headers)).json()["data"]
    assert lst["total"] >= 2  # superadmin + 新号
    assert any(it["id"] == u["id"] for it in lst["items"])


@pytest.mark.asyncio
async def test_create_rejects_external_role_and_weak_password(client, superadmin_headers):
    r = await client.post("/api/v1/users", headers=superadmin_headers, json={
        "email": "buyer@x.com", "name": "买家", "password": "Aa123456789", "role": "BUYER"})
    assert r.status_code == 400  # service 白名单硬挡(单一源头 ALLOWED_INTERNAL_ROLES)
    r2 = await client.post("/api/v1/users", headers=superadmin_headers, json={
        "email": "weak@x.com", "name": "弱", "password": "123", "role": "SALES"})
    assert r2.status_code == 422  # schema 强度校验


@pytest.mark.asyncio
async def test_create_email_conflict(client, superadmin_headers):
    await _create(client, superadmin_headers, email="dup@fulfillment.local")
    r = await client.post("/api/v1/users", headers=superadmin_headers, json={
        "email": "dup@fulfillment.local", "name": "乙", "password": "Aa123456789",
        "role": "SALES"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_list_filter_q_and_status(client, superadmin_headers):
    u = await _create(client, superadmin_headers, email="findme@fulfillment.local",
                      name="阿尔法销售")
    await client.post(f"/api/v1/users/{u['id']}/disable", headers=superadmin_headers)

    kw = (await client.get("/api/v1/users?q=阿尔法", headers=superadmin_headers)).json()["data"]
    assert kw["total"] >= 1 and any(it["id"] == u["id"] for it in kw["items"])
    dis = (await client.get("/api/v1/users?status=DISABLED",
                            headers=superadmin_headers)).json()["data"]
    assert all(it["status"] == "DISABLED" for it in dis["items"])
    assert any(it["id"] == u["id"] for it in dis["items"])


@pytest.mark.asyncio
async def test_update_user_info(client, superadmin_headers):
    u = await _create(client, superadmin_headers, email="edit@fulfillment.local")
    r = await client.put(f"/api/v1/users/{u['id']}", headers=superadmin_headers,
                         json={"name": "改名", "phone": "+255700000001"})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["name"] == "改名" and d["phone"] == "+255700000001" and d["roles"] == ["SALES"]


@pytest.mark.asyncio
async def test_update_super_admin_email_blocked(client, superadmin_headers, db_session):
    """守卫锚点保护:任何人(含 super admin 自己)不能改 super admin 的邮箱,
    否则「先改邮箱再重置/停用」两步绕过 super 守卫。name/phone 仍可改。"""
    sa_id = await _super_id(db_session)
    r = await client.put(f"/api/v1/users/{sa_id}", headers=superadmin_headers,
                         json={"email": "hijack@fulfillment.local"})
    assert r.status_code == 400
    ok = await client.put(f"/api/v1/users/{sa_id}", headers=superadmin_headers,
                          json={"name": "零号改名"})
    assert ok.status_code == 200 and ok.json()["data"]["name"] == "零号改名"


@pytest.mark.asyncio
async def test_update_other_admin_email_still_allowed(client, superadmin_headers):
    """非 super 的 ADMIN 邮箱仍可正常编辑(守卫只锚定零号)。"""
    u = await _create(client, superadmin_headers, email="admin5@fulfillment.local",
                      name="管理员五号", role="ADMIN")
    r = await client.put(f"/api/v1/users/{u['id']}", headers=superadmin_headers,
                         json={"email": "admin5new@fulfillment.local"})
    assert r.status_code == 200 and r.json()["data"]["email"] == "admin5new@fulfillment.local"


@pytest.mark.asyncio
async def test_disable_self_blocked_and_toggle_idempotent(client, superadmin_headers, db_session):
    sa_id = await _super_id(db_session)
    # superadmin 停自己:先撞「不能停用自己」守卫
    assert (await client.post(f"/api/v1/users/{sa_id}/disable",
                              headers=superadmin_headers)).status_code == 400

    u = await _create(client, superadmin_headers, email="toggle@fulfillment.local")
    d1 = await client.post(f"/api/v1/users/{u['id']}/disable", headers=superadmin_headers)
    d2 = await client.post(f"/api/v1/users/{u['id']}/disable", headers=superadmin_headers)
    assert d1.status_code == d2.status_code == 200
    assert d2.json()["data"]["status"] == "DISABLED"
    e = await client.post(f"/api/v1/users/{u['id']}/enable", headers=superadmin_headers)
    assert e.json()["data"]["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_disable_super_admin_blocked_via_other_admin(client, superadmin_headers, db_session):
    sa_id = await _super_id(db_session)
    await _create(client, superadmin_headers, email="admin2@fulfillment.local",
                  name="管理员二号", role="ADMIN", must_change=False)
    r = await client.post("/api/v1/auth/login", json={
        "identifier": "admin2@fulfillment.local", "password": "Aa123456789"})
    h2 = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    assert (await client.post(f"/api/v1/users/{sa_id}/disable", headers=h2)).status_code == 400


@pytest.mark.asyncio
async def test_last_admin_guard_service_level(db_session, superadmin_headers, monkeypatch):
    """守卫纵深:把 SUPER_ADMIN_EMAIL 指向不存在地址,种子管理员失去 super 保护后
    它是唯一 ACTIVE ADMIN → 停用应被「最后一个 ADMIN」守卫拦截(正常配置下该分支
    被 super 守卫前置遮蔽,故此处用 monkeypatch 暴露)。"""
    from app.core.exceptions import ValidationFailedError
    from app.services.user_service import disable_user

    sa_id = await _super_id(db_session)
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAIL", "nobody@nowhere.local")
    with pytest.raises(ValidationFailedError):
        await disable_user(db_session, target_user_id=sa_id,
                           actor_user_id=0, actor_user_email="t@t")


@pytest.mark.asyncio
async def test_users_admin_endpoints_require_user_manage(client, sales_headers):
    """SALES 无 user:manage:列表/建号均 403(/selectable 不受影响另有测试)。"""
    assert (await client.get("/api/v1/users", headers=sales_headers)).status_code == 403
    assert (await client.post("/api/v1/users", headers=sales_headers, json={
        "email": "x@x.com", "name": "x", "password": "Aa123456789",
        "role": "SALES"})).status_code == 403
