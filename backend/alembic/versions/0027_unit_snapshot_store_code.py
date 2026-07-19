"""0027 单据行 unit_snapshot 改存 units.code(data-only,4 张行表)

背景:`unit_snapshot` 早先冻结的是**展示文字**,且按该单的**报价语言**渲染(en 单存 "bag"、
zh 单存 "包"),导致内部中文界面单位列中英混排——报价语言是对客户的单据语言,不是内部界面
语言。单位是主数据、`units.code` 永久不变、语义不漂,无需像 name/spec 那样冻结展示值;且
「机器码列禁中文」是本仓硬规则。故本迁移把 4 张行表的存量展示值统一换成 code,展示时再翻译
(app/services/unit_service.py)。列类型不变(String(20)),只是语义从展示值变 code。

逻辑(全部 set-based,无逐行循环;幂等,可重跑):
① 防御断言:扫 4 表全部 distinct 非空 `unit_snapshot`,凡「既不等于任一 units.code、也无法
   经 units.label_i18n 任一语言值反查到**唯一** code」的 → raise RuntimeError 列出具体值,
   alembic 单事务整体回滚。**不做「查不到就保留原值」的静默兜底**——那会让 code 与展示文字
   混进同一列,比迁移失败难查得多。空串跳过(模型 default="",表示"无单位",本就无可翻译)。
② 4 条 UPDATE:仅改「不等于任何 code」的行(已是 code 的原样不动 ⇒ 幂等),按 label→code
   唯一映射换成 code。

downgrade:反向把 code 换回 `label_i18n->>'zh'` 中文标签。**注意这不是逐行忠实还原**:旧列
把展示值与单据语言绑在一起,en 单原本存的是 "bag" 而非 "包",降级后统一成中文。这是旧模型
自身的信息丢失(正是本迁移要消除的缺陷),不是降级实现的偷工;需精确回到降级前的逐行原值请
从备份恢复。无 zh 标签的 code 保持不动。

Revision ID: 0027_unit_snapshot_store_code
Revises: 0026_receivable
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027_unit_snapshot_store_code"
down_revision: Union[str, None] = "0026_receivable"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

# 4 张持有 unit_snapshot 快照的单据行表(出库单行不存快照,它 join 销售单行取)。
_LINE_TABLES = (
    "quotation_lines",
    "sales_order_lines",
    "purchase_order_lines",
    "inbound_order_lines",
)

# label_i18n 展开成 (code, label) —— 一个 code 的每种语言值各一行。
_LABELS_CTE = """
    labels AS (
        SELECT u.code AS code, l.value AS label
        FROM units u, jsonb_each_text(u.label_i18n) AS l
        WHERE l.value <> ''
    )
"""

# label → code 的**唯一**映射(同一 label 落到多个 code 的一律排除,由 ① 断言兜住)。
_UNIQUE_MAP_CTE = """
    label_to_code AS (
        SELECT label, min(code) AS code
        FROM labels
        GROUP BY label
        HAVING count(DISTINCT code) = 1
    )
"""


def _distinct_values_sql() -> str:
    return " UNION ".join(
        f"SELECT DISTINCT unit_snapshot AS v FROM {t} WHERE unit_snapshot <> ''"
        for t in _LINE_TABLES
    )


def upgrade() -> None:
    conn = op.get_bind()

    # ① 防御断言:任何不可唯一映射的值都中止迁移(不静默兜底)。
    unmappable = conn.execute(sa.text(f"""
        WITH {_LABELS_CTE},
        {_UNIQUE_MAP_CTE},
        vals AS ({_distinct_values_sql()})
        SELECT v.v
        FROM vals v
        WHERE NOT EXISTS (SELECT 1 FROM units u WHERE u.code = v.v)
          AND NOT EXISTS (SELECT 1 FROM label_to_code m WHERE m.label = v.v)
        ORDER BY v.v
    """)).scalars().all()
    if unmappable:
        raise RuntimeError(
            "0027 中止:以下 unit_snapshot 值既不是 units.code,也无法经 units.label_i18n "
            f"反查到唯一 code(请先人工订正 units 主数据或这些行再重跑):{list(unmappable)}"
        )

    # ①b 碰撞断言:某单位的 label 恰好等于**另一个**单位的 code 时,②的 `NOT EXISTS(code=值)`
    # 会把该行当成"已是 code"跳过,留下一个合法但**指向错单位**的 code —— 静默错映射,①查不出
    # (①只问"能否映射",不问"会否撞车")。故独立断言,发现即中止。
    collisions = conn.execute(sa.text(f"""
        WITH {_LABELS_CTE}
        SELECT l.label || ' → ' || l.code || ' / ' || u.code
        FROM labels l JOIN units u ON u.code = l.label AND u.code <> l.code
        ORDER BY 1
    """)).scalars().all()
    if collisions:
        raise RuntimeError(
            "0027 中止:某单位的 label 与另一单位的 code 同名,展示值→code 的反查会错映射"
            f"(label → 标签所属code / 同名的另一code):{list(collisions)}"
        )

    # ② 展示值 → code(已是 code 的不动 ⇒ 幂等)。
    for table in _LINE_TABLES:
        conn.execute(sa.text(f"""
            WITH {_LABELS_CTE},
            {_UNIQUE_MAP_CTE}
            UPDATE {table} t
            SET unit_snapshot = m.code
            FROM label_to_code m
            WHERE t.unit_snapshot = m.label
              AND NOT EXISTS (SELECT 1 FROM units u WHERE u.code = t.unit_snapshot)
        """))


def downgrade() -> None:
    conn = op.get_bind()
    for table in _LINE_TABLES:
        conn.execute(sa.text(f"""
            UPDATE {table} t
            SET unit_snapshot = u.label_i18n->>'zh'
            FROM units u
            WHERE u.code = t.unit_snapshot
              AND coalesce(u.label_i18n->>'zh', '') <> ''
              AND u.label_i18n->>'zh' <> t.unit_snapshot
        """))
