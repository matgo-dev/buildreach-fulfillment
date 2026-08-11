"""角色权限矩阵 + 自定义只读角色管理。"""
import pytest
from sqlalchemy import select

from app.audit.constants import AuditAction, AuditResourceType
from app.db.models.audit_log import AuditLog
from app.db.models.permission import Permission
from app.db.models.role import Role
from app.db.models.role_permission import RolePermission
from app.rbac.constants import Permissions


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
    assert admin["is_system"] is True
    assert admin["is_custom_readonly"] is False


@pytest.mark.asyncio
async def test_list_roles_requires_role_manage(client, sales_headers, purchaser_headers):
    r = await client.get("/api/v1/roles", headers=sales_headers)
    assert r.status_code == 403

    r2 = await client.get("/api/v1/roles", headers=purchaser_headers)
    assert r2.status_code == 403


@pytest.mark.asyncio
async def test_custom_readonly_role_lifecycle(client, superadmin_headers, db_session):
    body = {
        "code": "viewer_basic",
        "name": "基础只读",
        "description": "看商品与销售",
        "permissions": ["product:read", "sales:read"],
    }
    r = await client.post("/api/v1/roles", headers=superadmin_headers, json=body)
    assert r.status_code == 200, r.text
    role = r.json()["data"]
    assert role["code"] == "VIEWER_BASIC"
    assert role["is_system"] is False
    assert role["is_custom_readonly"] is True
    codes = {p["code"] for p in role["permissions"]}
    assert {"auth:login", "auth:logout", "auth:me", "product:read", "sales:read"} <= codes
    assert "sales:manage" not in codes

    r2 = await client.put("/api/v1/roles/VIEWER_BASIC", headers=superadmin_headers, json={
        "name": "基础只读改",
        "description": "",
        "permissions": ["inventory:read"],
    })
    assert r2.status_code == 200, r2.text
    updated = r2.json()["data"]
    assert updated["description"] is None
    codes2 = {p["code"] for p in updated["permissions"]}
    assert "inventory:read" in codes2
    assert "sales:read" not in codes2

    listed = (await client.get("/api/v1/roles", headers=superadmin_headers)).json()["data"]
    assert any(it["code"] == "VIEWER_BASIC" and it["name"] == "基础只读改" for it in listed)

    rd = await client.delete("/api/v1/roles/VIEWER_BASIC", headers=superadmin_headers)
    assert rd.status_code == 200, rd.text

    audit_rows = (await db_session.execute(
        select(AuditLog)
        .where(
            AuditLog.resource_type == AuditResourceType.ROLE,
            AuditLog.resource_id == "VIEWER_BASIC",
        )
        .order_by(AuditLog.id)
    )).scalars().all()
    assert [row.action for row in audit_rows] == [
        AuditAction.CREATE,
        AuditAction.UPDATE,
        AuditAction.DELETE,
    ]
    assert audit_rows[0].extra["new_permissions"] == [
        "auth:login", "auth:logout", "auth:me", "product:read", "sales:read",
    ]
    assert audit_rows[1].extra["old_permissions"] == [
        "auth:login", "auth:logout", "auth:me", "product:read", "sales:read",
    ]
    assert audit_rows[1].extra["new_permissions"] == [
        "auth:login", "auth:logout", "auth:me", "inventory:read",
    ]
    assert audit_rows[2].extra["old_permissions"] == [
        "auth:login", "auth:logout", "auth:me", "inventory:read",
    ]


@pytest.mark.asyncio
async def test_legacy_non_system_write_role_is_not_treated_as_custom_readonly(
    client,
    superadmin_headers,
    db_session,
):
    role = Role(code="LEGACY_MANAGER", name="遗留写角色")
    db_session.add(role)
    await db_session.flush()
    perms = (await db_session.execute(
        select(Permission).where(Permission.code.in_([
            Permissions.AUTH_LOGIN,
            Permissions.AUTH_LOGOUT,
            Permissions.AUTH_ME,
            Permissions.ROLE_MANAGE,
        ]))
    )).scalars().all()
    for perm in perms:
        db_session.add(RolePermission(role_id=role.id, permission_id=perm.id))
    await db_session.commit()

    listed = (await client.get("/api/v1/roles", headers=superadmin_headers)).json()["data"]
    legacy = next(it for it in listed if it["code"] == "LEGACY_MANAGER")
    assert legacy["is_system"] is False
    assert legacy["is_custom_readonly"] is False

    create_user = await client.post("/api/v1/users", headers=superadmin_headers, json={
        "email": "legacy-manager@fulfillment.local",
        "name": "遗留角色用户",
        "password": "Aa123456789",
        "roles": ["LEGACY_MANAGER"],
        "must_change_password": False,
    })
    assert create_user.status_code == 400
    assert "自定义只读角色" in create_user.text

    edit = await client.put("/api/v1/roles/LEGACY_MANAGER", headers=superadmin_headers, json={
        "name": "不应可编辑",
        "permissions": ["product:read"],
    })
    assert edit.status_code == 400
    assert "自定义只读角色" in edit.text

    delete_resp = await client.delete("/api/v1/roles/LEGACY_MANAGER", headers=superadmin_headers)
    assert delete_resp.status_code == 400
    assert "自定义只读角色" in delete_resp.text


@pytest.mark.asyncio
async def test_custom_role_rejects_write_and_system_role_mutation(client, superadmin_headers):
    assert (await client.post("/api/v1/roles", headers=superadmin_headers, json={
        "code": "BAD_WRITER",
        "name": "错误写角色",
        "permissions": ["sales:manage"],
    })).status_code == 400

    assert (await client.post("/api/v1/roles", headers=superadmin_headers, json={
        "code": "ADMIN",
        "name": "覆盖系统角色",
        "permissions": ["product:read"],
    })).status_code == 400

    assert (await client.put("/api/v1/roles/SALES", headers=superadmin_headers, json={
        "name": "销售改坏",
        "permissions": ["product:read"],
    })).status_code == 400


@pytest.mark.asyncio
async def test_cannot_delete_assigned_custom_role(client, superadmin_headers):
    r = await client.post("/api/v1/roles", headers=superadmin_headers, json={
        "code": "VIEWER_ASSIGNED",
        "name": "已分配只读",
        "permissions": ["product:read"],
    })
    assert r.status_code == 200, r.text
    u = await client.post("/api/v1/users", headers=superadmin_headers, json={
        "email": "viewer-assigned@fulfillment.local",
        "name": "已分配用户",
        "password": "Aa123456789",
        "roles": ["VIEWER_ASSIGNED"],
        "must_change_password": False,
    })
    assert u.status_code == 200, u.text
    rd = await client.delete("/api/v1/roles/VIEWER_ASSIGNED", headers=superadmin_headers)
    assert rd.status_code == 400
