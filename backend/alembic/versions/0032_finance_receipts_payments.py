"""0032 财务:receipts / payments / receipt_allocations / payment_allocations(财务功能迁移)
+ receivables/payables 账龄查询 partial composite 索引(F1,增长型性能雷修复)

主流程第11步(收尾节点),契约 docs/契约/2026-07-21-0135-财务增量-设计契约.md §1。
实层(收款单/付款单,人工登记一笔到账/付款)+ 核销层(把钱勾到应收/应付账层)。

- receipts:收侧实层。customer_id **可空** = 待认领(D1 不对称);amount_unallocated 生成列
  = 未分配余额 = 预收;status 纯派生不落列;void = 纠错口(D11)。
- payments:付侧实层,🔴红线。supplier_id 必填(无待认领);paid_at(付款日,≠ 到账日)。
- receipt_allocations / payment_allocations:核销层。偏唯一(一对活动核销至多一条);
  reversed_at = 反核销软删留痕;alloc_type ∈ {AUTO,MANUAL};全 FK 全量索引(F2)。
- NumberScope RECEIPT/PAYMENT 号段:应用层 allocate() 首用即 INSERT,迁移不预插(codegen 单一源头)。
- 账层不改列,但追加两条账龄 partial composite 索引:自动核销候选查询(按客户/供应商 + 币种 +
  未结清 + 账龄序)走索引、排除已结清行,翻 100 倍不退化(§1.1 F1)。

Revision ID: 0032_finance_receipts_payments
Revises: 0031_customs_declarations
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032_finance_receipts_payments"
down_revision: Union[str, None] = "0031_customs_declarations"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # ---------- receipts(收侧实层)----------
    op.create_table(
        "receipts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("receipt_no", sa.String(length=24), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),   # 可空 = 待认领
        sa.Column("account_info", sa.String(length=200), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("amount_allocated", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("amount_unallocated", sa.Numeric(precision=18, scale=2),
                  sa.Computed("amount - amount_allocated", persisted=True)),
        sa.Column("received_at", sa.Date(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column("voided_by", sa.Integer(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["voided_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("receipt_no", name="uq_receipts_receipt_no"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_receipts_currency_iso4217"),
        sa.CheckConstraint("amount > 0", name="ck_receipts_amount_pos"),
        sa.CheckConstraint("amount_allocated >= 0 AND amount_allocated <= amount",
                           name="ck_receipts_allocated_range"),
    )
    op.create_index(op.f("ix_receipts_customer_id"), "receipts", ["customer_id"])
    op.create_index(op.f("ix_receipts_voided_at"), "receipts", ["voided_at"])
    op.create_index(op.f("ix_receipts_voided_by"), "receipts", ["voided_by"])
    op.create_index(op.f("ix_receipts_created_by"), "receipts", ["created_by"])

    # ---------- payments(付侧实层,🔴红线)----------
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("payment_no", sa.String(length=24), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),   # 必填(无待认领)
        sa.Column("account_info", sa.String(length=200), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("amount_allocated", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("amount_unallocated", sa.Numeric(precision=18, scale=2),
                  sa.Computed("amount - amount_allocated", persisted=True)),
        sa.Column("paid_at", sa.Date(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column("voided_by", sa.Integer(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["voided_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_no", name="uq_payments_payment_no"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_payments_currency_iso4217"),
        sa.CheckConstraint("amount > 0", name="ck_payments_amount_pos"),
        sa.CheckConstraint("amount_allocated >= 0 AND amount_allocated <= amount",
                           name="ck_payments_allocated_range"),
    )
    op.create_index(op.f("ix_payments_supplier_id"), "payments", ["supplier_id"])
    op.create_index(op.f("ix_payments_voided_at"), "payments", ["voided_at"])
    op.create_index(op.f("ix_payments_voided_by"), "payments", ["voided_by"])
    op.create_index(op.f("ix_payments_created_by"), "payments", ["created_by"])

    # ---------- receipt_allocations(核销层,收侧)----------
    op.create_table(
        "receipt_allocations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("receipt_id", sa.Integer(), nullable=False),
        sa.Column("receivable_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("alloc_type", sa.String(length=16), nullable=False),
        sa.Column("reversed_at", sa.DateTime(), nullable=True),
        sa.Column("reversed_by", sa.Integer(), nullable=True),
        sa.Column("reverse_reason", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["receipt_id"], ["receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["receivable_id"], ["receivables.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reversed_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("amount > 0", name="ck_receipt_alloc_amount_pos"),
        sa.CheckConstraint("alloc_type IN ('AUTO','MANUAL')", name="ck_receipt_alloc_type"),
    )
    op.create_index(op.f("ix_receipt_allocations_receipt_id"), "receipt_allocations",
                    ["receipt_id"])
    op.create_index(op.f("ix_receipt_allocations_receivable_id"), "receipt_allocations",
                    ["receivable_id"])
    op.create_index(op.f("ix_receipt_allocations_reversed_by"), "receipt_allocations",
                    ["reversed_by"])
    op.create_index(op.f("ix_receipt_allocations_created_by"), "receipt_allocations",
                    ["created_by"])
    # 偏唯一:一笔收款对一张应收至多一条活动核销(部分核销靠 amount;反核销留痕后可再建)。
    op.create_index("uq_receipt_alloc_active", "receipt_allocations",
                    ["receipt_id", "receivable_id"], unique=True,
                    postgresql_where=sa.text("reversed_at IS NULL"))

    # ---------- payment_allocations(核销层,付侧)----------
    op.create_table(
        "payment_allocations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("payment_id", sa.Integer(), nullable=False),
        sa.Column("payable_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("alloc_type", sa.String(length=16), nullable=False),
        sa.Column("reversed_at", sa.DateTime(), nullable=True),
        sa.Column("reversed_by", sa.Integer(), nullable=True),
        sa.Column("reverse_reason", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["payable_id"], ["payables.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reversed_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("amount > 0", name="ck_payment_alloc_amount_pos"),
        sa.CheckConstraint("alloc_type IN ('AUTO','MANUAL')", name="ck_payment_alloc_type"),
    )
    op.create_index(op.f("ix_payment_allocations_payment_id"), "payment_allocations",
                    ["payment_id"])
    op.create_index(op.f("ix_payment_allocations_payable_id"), "payment_allocations",
                    ["payable_id"])
    op.create_index(op.f("ix_payment_allocations_reversed_by"), "payment_allocations",
                    ["reversed_by"])
    op.create_index(op.f("ix_payment_allocations_created_by"), "payment_allocations",
                    ["created_by"])
    op.create_index("uq_payment_alloc_active", "payment_allocations",
                    ["payment_id", "payable_id"], unique=True,
                    postgresql_where=sa.text("reversed_at IS NULL"))

    # ---------- 账层账龄 partial composite 索引(F1)----------
    # 自动核销候选:WHERE customer/supplier + currency + voided_at IS NULL + balance>0
    # ORDER BY due_at, created_at, id —— 过滤 + 锁序一并走索引,排除已结清行,翻量不退化。
    # 谓词含生成列 balance(persisted),PG 接受(实测)。
    op.create_index("ix_receivables_open_aging", "receivables",
                    ["customer_id", "currency", "due_at", "created_at", "id"],
                    postgresql_where=sa.text("voided_at IS NULL AND balance > 0"))
    op.create_index("ix_payables_open_aging", "payables",
                    ["supplier_id", "currency", "due_at", "created_at", "id"],
                    postgresql_where=sa.text("voided_at IS NULL AND balance > 0"))


def downgrade() -> None:
    op.drop_index("ix_payables_open_aging", table_name="payables")
    op.drop_index("ix_receivables_open_aging", table_name="receivables")

    op.drop_index("uq_payment_alloc_active", table_name="payment_allocations")
    op.drop_index(op.f("ix_payment_allocations_created_by"), table_name="payment_allocations")
    op.drop_index(op.f("ix_payment_allocations_reversed_by"), table_name="payment_allocations")
    op.drop_index(op.f("ix_payment_allocations_payable_id"), table_name="payment_allocations")
    op.drop_index(op.f("ix_payment_allocations_payment_id"), table_name="payment_allocations")
    op.drop_table("payment_allocations")

    op.drop_index("uq_receipt_alloc_active", table_name="receipt_allocations")
    op.drop_index(op.f("ix_receipt_allocations_created_by"), table_name="receipt_allocations")
    op.drop_index(op.f("ix_receipt_allocations_reversed_by"), table_name="receipt_allocations")
    op.drop_index(op.f("ix_receipt_allocations_receivable_id"), table_name="receipt_allocations")
    op.drop_index(op.f("ix_receipt_allocations_receipt_id"), table_name="receipt_allocations")
    op.drop_table("receipt_allocations")

    op.drop_index(op.f("ix_payments_created_by"), table_name="payments")
    op.drop_index(op.f("ix_payments_voided_by"), table_name="payments")
    op.drop_index(op.f("ix_payments_voided_at"), table_name="payments")
    op.drop_index(op.f("ix_payments_supplier_id"), table_name="payments")
    op.drop_table("payments")

    op.drop_index(op.f("ix_receipts_created_by"), table_name="receipts")
    op.drop_index(op.f("ix_receipts_voided_by"), table_name="receipts")
    op.drop_index(op.f("ix_receipts_voided_at"), table_name="receipts")
    op.drop_index(op.f("ix_receipts_customer_id"), table_name="receipts")
    op.drop_table("receipts")
    # NumberScope RECEIPT/PAYMENT 号段种子由应用层 allocate() 首用创建(迁移未插),无需 DELETE。
