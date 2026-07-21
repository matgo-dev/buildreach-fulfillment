"""0030 附件:attachments 全局基建独立表(单据扫描件的文件注册)

首个消费者 = 报关记录(0031 追加归属 FK 列)。全局基建表,**独立迁移**(不生在功能迁移):
- file_key:服务端生成的不透明随机键(uuid4 系),UNIQUE;严禁由用户文件名派生;
  Storage 层 key→路径解析带穿越守卫(见 storage.py 的 key 校验器)。
- size_bytes:BIGINT + CHECK(> 0);大小上限走应用层配置(ATTACHMENT_MAX_SIZE_BYTES),不落 CHECK。
- created_by:上传者=创建者(不另设 uploaded_by,单一源头),FK RESTRICT + 单列索引。
- deleted_at 软删(SoftDeleteMixin,timezone=True);created_at/updated_at naive UTC。

本迁移只建纯文件注册表(无业务归属列)。归属 FK 列(customs_declaration_id)+ 孤儿配额
偏索引由 0031 功能迁移追加。

Revision ID: 0030_attachments
Revises: 0029_shipment_events
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0030_attachments"
down_revision: Union[str, None] = "0029_shipment_events"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("file_key", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("size_bytes > 0", name="ck_attachments_size_positive"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_key", name="uq_attachments_file_key"),
    )
    op.create_index("ix_attachments_created_by", "attachments", ["created_by"])


def downgrade() -> None:
    op.drop_index("ix_attachments_created_by", table_name="attachments")
    op.drop_table("attachments")
