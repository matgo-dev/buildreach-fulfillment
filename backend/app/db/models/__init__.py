"""模型注册 —— 供 Base.metadata(create_all / alembic autogenerate)发现所有表。"""
from app.db.models.user import User
from app.db.models.role import Role, RoleCode
from app.db.models.permission import Permission
from app.db.models.user_role import UserRole
from app.db.models.role_permission import RolePermission
from app.db.models.audit_log import AuditLog
from app.db.models.category import Category  # noqa: F401
from app.db.models.category_spec_suggestion import CategorySpecSuggestion  # noqa: F401
from app.db.models.customer import Customer  # noqa: F401
from app.db.models.number_sequence import NumberSequence  # noqa: F401
from app.db.models.spu import Spu  # noqa: F401
from app.db.models.sku import Sku  # noqa: F401
from app.db.models.quotation import QuotationOrder, QuotationLine  # noqa: F401

__all__ = [
    "User", "Role", "RoleCode", "Permission",
    "UserRole", "RolePermission", "AuditLog", "Category",
    "CategorySpecSuggestion", "Customer", "NumberSequence", "Spu", "Sku",
    "QuotationOrder", "QuotationLine",
]
