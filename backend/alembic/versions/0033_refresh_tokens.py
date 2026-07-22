"""0033 auth:refresh token 家族账本(轮换作废 + 重放检测 + 单会话吊销)

两张表:`refresh_token_families`(组级承载行,`revoked_at` = 族级「已撤」单一源头)+
`refresh_tokens`(成员行,只存 jti 的 sha256 哈希不存原文)。一次登录开一族;refresh 轮换在
同族派生后继并标父行 used;重放/登出撤族 = 锁族行写 revoked_at,派生成员前先锁族行 → 与撤族
串行,杜绝并发派生的幻影成员逃逸(错题集 A8:组级不变量须有组级锁点,不靠成员级 set-based 写)。
与 users.token_version(全局总闸)分工,family = 单会话精确掐断。过期成员由登录成功路径惰性
清理(DELETE WHERE expires_at <= now),清空后的空族一并删除。

Revision ID: 0033_refresh_tokens
Revises: 0032_finance_receipts_payments
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0033_refresh_tokens"
down_revision: Union[str, None] = "0032_finance_receipts_payments"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # 组级承载行:族级「已撤」事实的单一源头。撤族=锁本行/原子 UPDATE(O(1));
    # refresh 派生成员前先锁本行 → 与撤族串行,杜绝并发派生的幻影成员逃逸(错题集 A8)。
    op.create_table(
        "refresh_token_families",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("revoked_at IS NULL OR revoked_at >= created_at",
                           name="ck_refresh_token_families_revoked_after_create"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    # FK 铁律全量索引。
    op.create_index("ix_refresh_token_families_user_id",
                    "refresh_token_families", ["user_id"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("family_id", sa.String(length=32), nullable=False),
        sa.Column("jti_hash", sa.String(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_jti_hash", sa.String(length=64), nullable=True),
        sa.CheckConstraint("expires_at > issued_at",
                           name="ck_refresh_tokens_expiry_after_issue"),
        sa.CheckConstraint("used_at IS NULL OR used_at >= issued_at",
                           name="ck_refresh_tokens_used_after_issue"),
        sa.CheckConstraint("(used_at IS NULL) = (replaced_by_jti_hash IS NULL)",
                           name="ck_refresh_tokens_used_replaced_paired"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        # 所属族(组级承载行)。RESTRICT:惰性清理先删成员后删空族,族行不可先于成员删。
        sa.ForeignKeyConstraint(["family_id"], ["refresh_token_families.id"],
                                ondelete="RESTRICT"),
        # 后继指针自引用 FK(SET NULL);目标 jti_hash 由下方 UNIQUE 约束在同一 CREATE TABLE 内提供。
        sa.ForeignKeyConstraint(["replaced_by_jti_hash"], ["refresh_tokens.jti_hash"],
                                ondelete="SET NULL"),
        # refresh 查库主路径 = 按 jti_hash 精确命中;唯一约束兼作查找索引 + 自引用 FK 目标。
        sa.UniqueConstraint("jti_hash", name="uq_refresh_tokens_jti_hash"),
        sa.PrimaryKeyConstraint("id"),
    )
    # FK 铁律全量索引。
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    # family 维度(撤族/清理空族的 join)与 FK 索引。
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])
    # 惰性清理谓词(DELETE WHERE expires_at <= now,登录路径触发)走索引;清理是明确查询路径。
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])
    # 自引用 FK 引用列:清理 DELETE 时 ON DELETE SET NULL 需按此列反查引用者,无索引即逐行扫。
    op.create_index("ix_refresh_tokens_replaced_by_jti_hash",
                    "refresh_tokens", ["replaced_by_jti_hash"])


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_replaced_by_jti_hash", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_expires_at", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    # uq_refresh_tokens_jti_hash 作为 UNIQUE 约束随 drop_table 一并移除。
    op.drop_table("refresh_tokens")
    op.drop_index("ix_refresh_token_families_user_id",
                  table_name="refresh_token_families")
    op.drop_table("refresh_token_families")
