"""0023 账号级登录锁定:users 加 failed_login_attempts / locked_until

进程内登录限流(services/rate_limit.py,identifier+ip 维度)重启即清、换 IP 可绕,
只作第一道减速带;锁定状态落用户行(最强层):连续失败达 ACCOUNT_LOCK_THRESHOLD →
置 locked_until(ACCOUNT_LOCK_MINUTES 后自动过期)并清零计数;登录成功 / 管理员
重置密码(人工解锁通道)清零并解除锁定。

Revision ID: 0023_account_lockout
Revises: 0022_spec_descriptor
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023_account_lockout"
down_revision: Union[str, None] = "0022_spec_descriptor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("failed_login_attempts", sa.Integer(),
                                     nullable=False, server_default=sa.text("0")))
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True),
                                     nullable=True))
    op.create_check_constraint("ck_users_failed_login_attempts_nn", "users",
                               "failed_login_attempts >= 0")


def downgrade() -> None:
    op.drop_constraint("ck_users_failed_login_attempts_nn", "users", type_="check")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_attempts")
