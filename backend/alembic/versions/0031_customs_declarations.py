"""0031 报关:customs_declarations 功能表 + attachments 归属 FK 列 + 孤儿配额偏索引

报关记录(发运柜子表,整柜一次报关,回填结果)。主流程第10步,契约
docs/契约/2026-07-21-0045-报关增量-设计契约.md §1.1/§1.2。

- customs_declarations:挂柜(shipment_order_id FK RESTRICT)+ created_by FK RESTRICT;
  declaration_no 外部报关单号(不占 NumberScope);declared_at/released_at Date;
  CHECK released_at ≥ declared_at;两个偏唯一(每柜至多一条活动 + 单号活动期唯一);
  shipment_order_id 全量索引(FK 铁律,偏唯一不算替代)。
- attachments 追加 customs_declaration_id(归属 FK 列,属功能不生在 0030 基建迁移);
  NULL = 孤儿。孤儿配额偏索引精确命中「某用户活动孤儿」谓词(不随其历史已归属附件增长)。

依赖顺序:先建 customs_declarations,再给 attachments 加指向它的 FK 列。

Revision ID: 0031_customs_declarations
Revises: 0030_attachments
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0031_customs_declarations"
down_revision: Union[str, None] = "0030_attachments"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "customs_declarations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shipment_order_id", sa.Integer(), nullable=False),
        sa.Column("declaration_no", sa.String(length=32), nullable=False),
        sa.Column("declared_at", sa.Date(), nullable=False),
        sa.Column("released_at", sa.Date(), nullable=True),
        sa.Column("declarant", sa.String(length=100), nullable=True),
        sa.Column("customs_office", sa.String(length=100), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("released_at IS NULL OR released_at >= declared_at",
                           name="ck_customs_released_ge_declared"),
        sa.ForeignKeyConstraint(["shipment_order_id"], ["shipment_orders.id"],
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customs_declarations_shipment", "customs_declarations",
                    ["shipment_order_id"])
    op.create_index("ix_customs_declarations_created_by", "customs_declarations",
                    ["created_by"])
    # 每柜至多一条活动报关(偏唯一;软删行退出约束)。
    op.create_index("uq_customs_active_shipment", "customs_declarations",
                    ["shipment_order_id"], unique=True,
                    postgresql_where=sa.text("deleted_at IS NULL"))
    # 报关单号活动期唯一(防重录)。
    op.create_index("uq_customs_active_declno", "customs_declarations",
                    ["declaration_no"], unique=True,
                    postgresql_where=sa.text("deleted_at IS NULL"))

    # attachments 追加归属 FK 列(属功能,不生在 0030 基建迁移)。NULL = 孤儿。
    op.add_column("attachments",
                  sa.Column("customs_declaration_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_attachments_customs_declaration", "attachments",
                          "customs_declarations", ["customs_declaration_id"], ["id"],
                          ondelete="RESTRICT")
    op.create_index("ix_attachments_customs_declaration", "attachments",
                    ["customs_declaration_id"])
    # 孤儿配额偏索引:精确命中「某用户的活动孤儿」谓词(created_by + 全归属列 NULL + 未删),
    # 不随其历史已归属附件增长。加平行归属 FK 列时须同步扩谓词为「全部归属列皆 NULL」。
    op.create_index("ix_attachments_orphan_quota", "attachments", ["created_by"],
                    postgresql_where=sa.text(
                        "customs_declaration_id IS NULL AND deleted_at IS NULL"))


def downgrade() -> None:
    op.drop_index("ix_attachments_orphan_quota", table_name="attachments")
    op.drop_index("ix_attachments_customs_declaration", table_name="attachments")
    op.drop_constraint("fk_attachments_customs_declaration", "attachments",
                       type_="foreignkey")
    op.drop_column("attachments", "customs_declaration_id")

    op.drop_index("uq_customs_active_declno", table_name="customs_declarations")
    op.drop_index("uq_customs_active_shipment", table_name="customs_declarations")
    op.drop_index("ix_customs_declarations_created_by", table_name="customs_declarations")
    op.drop_index("ix_customs_declarations_shipment", table_name="customs_declarations")
    op.drop_table("customs_declarations")
