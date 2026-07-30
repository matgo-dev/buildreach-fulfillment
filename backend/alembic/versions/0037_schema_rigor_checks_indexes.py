"""0037 schema 严谨补齐:users/audit_logs 状态 CHECK + 清 users 冗余非唯一索引

走查补漏(纯 DDL,无数据变更):
- users.status 补 CHECK IN ('ACTIVE','DISABLED','DEACTIVATED')：全库唯一漏状态兜底的业务表,
  恰是账号封禁/注销的承载列,与 spus/customers 等 status CHECK 同纪律补齐。
- audit_logs.status 补 CHECK IN ('SUCCESS','FAILED')。
- 删 ix_users_email / ix_users_username / ix_users_phone：与同列 uq_users_* 唯一索引重复
  (唯一 btree 已覆盖该列全部等值/排序查询),纯冗余、写放大。
- 删 ix_spus_category_code：与 ix_spus_category_code_prefix(text_pattern_ops)重复。实测全仓
  对 category_code 仅等值 + 前缀 LIKE(list_spus 子树过滤)、零 locale 排序/范围,pattern_ops
  索引全覆盖,默认 opclass 普通索引纯冗余。

Revision ID: 0037_schema_rigor_checks_indexes
Revises: 0036_fix_header_amount_rounding
"""
from __future__ import annotations

from typing import Union

from alembic import op

revision: str = "0037_schema_rigor_checks_indexes"
down_revision: Union[str, None] = "0036_fix_header_amount_rounding"
branch_labels = None
depends_on = None

_REDUNDANT_USER_INDEXES = ("ix_users_email", "ix_users_username", "ix_users_phone")


def upgrade() -> None:
    op.create_check_constraint(
        "ck_users_status", "users",
        "status IN ('ACTIVE','DISABLED','DEACTIVATED')")
    op.create_check_constraint(
        "ck_audit_logs_status", "audit_logs",
        "status IN ('SUCCESS','FAILED')")
    for name in _REDUNDANT_USER_INDEXES:
        op.drop_index(name, table_name="users")
    op.drop_index("ix_spus_category_code", table_name="spus")


def downgrade() -> None:
    op.create_index("ix_spus_category_code", "spus", ["category_code"])
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_phone", "users", ["phone"])
    op.drop_constraint("ck_audit_logs_status", "audit_logs", type_="check")
    op.drop_constraint("ck_users_status", "users", type_="check")
