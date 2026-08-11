from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, MetaData, Numeric, Table

from scripts import schema_lint


def test_schema_lint_flags_id_columns_without_fk():
    table = Table("orders", MetaData(), Column("customer_id", Integer))

    assert list(schema_lint._lint_missing_foreign_keys(table)) == [
        "orders.customer_id: looks like an FK column but has no ForeignKey"
    ]


def test_schema_lint_accepts_real_fk_columns():
    metadata = MetaData()
    Table("customers", metadata, Column("id", Integer, primary_key=True))
    table = Table("orders", metadata, Column("customer_id", Integer, ForeignKey("customers.id")))

    assert list(schema_lint._lint_missing_foreign_keys(table)) == []


def test_schema_lint_flags_money_quantity_columns_without_check():
    table = Table("payments", MetaData(), Column("amount", Numeric(12, 2)))

    assert list(schema_lint._lint_missing_numeric_checks(table)) == [
        "payments.amount: money/quantity-like column has no CheckConstraint"
    ]


def test_schema_lint_accepts_money_quantity_columns_with_check():
    table = Table(
        "payments",
        MetaData(),
        Column("amount", Numeric(12, 2)),
        CheckConstraint("amount >= 0", name="ck_payments_amount_nonnegative"),
    )

    assert list(schema_lint._lint_missing_numeric_checks(table)) == []


def test_schema_lint_flags_cjk_machine_values_in_checks():
    table = Table(
        "orders",
        MetaData(),
        Column("status", Integer),
        CheckConstraint("status IN ('已确认')", name="ck_orders_status"),
    )

    assert list(schema_lint._lint_cjk_machine_values(table)) == [
        "orders: CheckConstraint contains CJK text: status IN ('已确认')"
    ]
