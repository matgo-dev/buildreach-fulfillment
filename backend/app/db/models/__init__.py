"""基座模型注册 —— 仅 auth/RBAC/审计。业务模型不在此。"""
from app.db.models.user import User
from app.db.models.role import Role, RoleCode
from app.db.models.permission import Permission
from app.db.models.user_role import UserRole
from app.db.models.role_permission import RolePermission
from app.db.models.audit_log import AuditLog

__all__ = [
    "User", "Role", "RoleCode", "Permission",
    "UserRole", "RolePermission", "AuditLog",
]
