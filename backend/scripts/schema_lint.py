"""数据库结构轻量 lint。

拦三类容易在多人迭代里反复出现的低级 schema 问题:
- 外键语义列(`*_id`)没有 FK;
- 金额 / 数量 / 单价 / 总额列没有 DB CHECK 兜底;
- CHECK 约束里把 code/status 等机器值写成中文。
"""
from __future__ import annotations

import re
import sys
from collections.abc import Iterable

from sqlalchemy import CheckConstraint
from sqlalchemy.sql.schema import Table
from sqlalchemy.sql.sqltypes import Float, Integer, Numeric

import app.db.models  # noqa: F401  模型注册副作用:填充 Base.metadata
from app.db.base import Base


FK_COLUMN_ALLOWLIST = {
    # request trace, not an entity FK.
    ("audit_logs", "trace_id"),
    # 审计留痕允许用户后续被删除/匿名化,不绑定 FK 生命周期。
    ("audit_logs", "user_id"),
    # 多态资源指针:由 resource_type + resource_id 解释。
    ("audit_logs", "resource_id"),
    # 角色作用域预留多态字段,由 scope 决定目标域。
    ("roles", "scope_id"),
    # 库存流水多态来源:由 source_type + source_id/source_line_id 指向入库/出库单据。
    ("inventory_movements", "source_id"),
    ("inventory_movements", "source_line_id"),
}

MONEY_AND_QUANTITY_HINTS = ("amount", "qty", "quantity", "price", "total", "balance")
CJK_RE = re.compile(r"[\u3400-\u9fff]")


def _check_texts(table: Table) -> list[str]:
    return [str(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)]


def _is_guarded_by_check(table: Table, column_name: str) -> bool:
    joined_checks = "\n".join(_check_texts(table)).lower()
    return column_name.lower() in joined_checks


def _lint_missing_foreign_keys(table: Table) -> Iterable[str]:
    for column in table.columns:
        if not column.name.endswith("_id"):
            continue
        if column.foreign_keys or (table.name, column.name) in FK_COLUMN_ALLOWLIST:
            continue
        yield f"{table.name}.{column.name}: looks like an FK column but has no ForeignKey"


def _lint_missing_numeric_checks(table: Table) -> Iterable[str]:
    for column in table.columns:
        if column.computed is not None:
            continue
        if not isinstance(column.type, (Float, Integer, Numeric)):
            continue
        if not any(hint in column.name.lower() for hint in MONEY_AND_QUANTITY_HINTS):
            continue
        if not _is_guarded_by_check(table, column.name):
            yield f"{table.name}.{column.name}: money/quantity-like column has no CheckConstraint"


def _lint_cjk_machine_values(table: Table) -> Iterable[str]:
    for text in _check_texts(table):
        if CJK_RE.search(text):
            yield f"{table.name}: CheckConstraint contains CJK text: {text}"


def main() -> int:
    errors: list[str] = []
    for table in sorted(Base.metadata.tables.values(), key=lambda t: t.name):
        errors.extend(_lint_missing_foreign_keys(table))
        errors.extend(_lint_missing_numeric_checks(table))
        errors.extend(_lint_cjk_machine_values(table))

    if errors:
        print("Schema lint failed:")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("Schema lint passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
