"""0032 auth:refresh_tokens 家族账本(轮换作废 + 重放检测 + 单会话吊销)

一次登录一个 token family;refresh 轮换在同族派生后继并标父行 used;重放撤整族、logout 撤本族。
只存 jti 的 sha256 哈希不存原文。与 users.token_version(全局总闸)分工,family = 单会话精确掐断。

⚠️ 迁移号占位:财务 PR#35 也领了 0032(receipts/payments,与本表不相交)。二者后合者
   须把本文件 revision 顺延、down_revision 改指对方 head —— 大概率财务先合 → 本迁移改
   `0033_refresh_tokens` / down_revision `0032_finance_receipts_payments`,零数据冲突。
   现基于 origin/main(head 0031)以 0032→0031 落地,便于本地实跑单 head 验证。

Revision ID: 0032_refresh_tokens
Revises: 0031_customs_declarations
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032_refresh_tokens"
down_revision: Union[str, None] = "0031_customs_declarations"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("family_id", sa.String(length=32), nullable=False),
        sa.Column("jti_hash", sa.String(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_jti_hash", sa.String(length=64), nullable=True),
        sa.CheckConstraint("expires_at > issued_at",
                           name="ck_refresh_tokens_expiry_after_issue"),
        sa.CheckConstraint("used_at IS NULL OR used_at >= issued_at",
                           name="ck_refresh_tokens_used_after_issue"),
        sa.CheckConstraint("revoked_at IS NULL OR revoked_at >= issued_at",
                           name="ck_refresh_tokens_revoked_after_issue"),
        sa.CheckConstraint("(used_at IS NULL) = (replaced_by_jti_hash IS NULL)",
                           name="ck_refresh_tokens_used_replaced_paired"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        # 后继指针自引用 FK(SET NULL);目标 jti_hash 由下方 UNIQUE 约束在同一 CREATE TABLE 内提供。
        sa.ForeignKeyConstraint(["replaced_by_jti_hash"], ["refresh_tokens.jti_hash"],
                                ondelete="SET NULL"),
        # refresh 查库主路径 = 按 jti_hash 精确命中;唯一约束兼作查找索引 + 自引用 FK 目标。
        sa.UniqueConstraint("jti_hash", name="uq_refresh_tokens_jti_hash"),
        sa.PrimaryKeyConstraint("id"),
    )
    # FK 铁律全量索引。
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    # family 维度撤销(登出 / 重放撤族)的查询列。
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])
    # 惰性清理谓词(DELETE WHERE expires_at < now)走索引;小表但清理是明确查询路径。
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_expires_at", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    # uq_refresh_tokens_jti_hash 作为 UNIQUE 约束随 drop_table 一并移除。
    op.drop_table("refresh_tokens")
