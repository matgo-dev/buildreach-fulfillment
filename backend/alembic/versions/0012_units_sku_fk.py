"""units 售卖单位专表 + sku.unit 由自由文本 String 收编为 FK(spec §11 Part A;M1 回补)

Revision ID: 0012_units_sku_fk
Revises: 0011_spu_category_prefix_idx

`sku.unit` 现为自由 `String(20)`(红线缺口:单位该存 code)。本迁移建 `units`
专表(code-as-PK,小查表、code 永久不变,同 categories.code 契约;ff-schema-review
#9 已记档此分歧),把 `sku.unit` 收编为 FK `units.code`(ON DELETE RESTRICT,在用
单位删不掉)。

upgrade 时序(写死,不走 autogenerate,与 0010 同款纪律):
  ① create `units`(4 列 + 2 CHECK:code 纯 ASCII 格式自证 + sort_order 非负;
     继承 TimestampUpdateMixin,不加 created_by——主数据操作者追溯走 audit_log)
  ② 迁移内 data-op 幂等 seed 常用单位(INSERT ... ON CONFLICT(code) DO NOTHING;
     不甩给 app seed.py——否则全新部署回填时无码可映、加 FK 会失败)
  ③ 回填现存 `sku.unit` 自由文本 → code(_UNIT_BACKFILL 映射字典;已是合法 code
     的原样放行,幂等)。映射不上的值**硬 fail**、不静默降级——要求人工确认真实
     历史取值后补映射字典再重跑(映射字典系上线前需按真实 DB 数据核对,当前仅
     覆盖本仓已知用例:PCS/pcs/米/个/件/吨/kg 等常见自由文本)。
  ④ 加 FK(ON DELETE RESTRICT)+ 索引 ix_skus_unit(RESTRICT 删检查 + 按单位筛选)

downgrade(有损,已明写):drop FK + 索引 → drop `units` → `sku.unit` 退回自由
String(20)。**不反译** code→原文(如 'piece' 原是"个"还是"pcs"不可知);code 本
是合法 String,留原地不变。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_units_sku_fk"
down_revision = "0011_spu_category_prefix_idx"
branch_labels = None
depends_on = None


# 常用售卖单位种子(code, label_i18n, sort_order)。code 纯 ASCII、稳定、永久不变。
_UNIT_SEEDS: list[tuple[str, dict, int]] = [
    ("piece", {"zh": "件", "en": "pc"}, 10),
    ("meter", {"zh": "米", "en": "m"}, 20),
    ("sqm", {"zh": "平方米", "en": "sqm"}, 30),
    ("cbm", {"zh": "立方米", "en": "cbm"}, 40),
    ("kg", {"zh": "千克", "en": "kg"}, 50),
    ("ton", {"zh": "吨", "en": "ton"}, 60),
    ("roll", {"zh": "卷", "en": "roll"}, 70),
    ("bag", {"zh": "包", "en": "bag"}, 80),
    ("box", {"zh": "箱", "en": "box"}, 90),
    ("set", {"zh": "套", "en": "set"}, 100),
    ("pair", {"zh": "双", "en": "pair"}, 110),
]

# 历史自由文本 → units.code 回填映射(上线前须按真实 DB 现存 sku.unit 取值核对补全)。
# 已是合法 code 的原样放行(幂等:重跑/正常路径均可)。
_UNIT_BACKFILL: dict[str, str] = {
    code: code for code, _, _ in _UNIT_SEEDS
} | {
    "PCS": "piece", "pcs": "piece", "Pcs": "piece", "个": "piece", "件": "piece",
    "米": "meter", "M": "meter", "m": "meter",
    "平方米": "sqm", "㎡": "sqm",
    "立方米": "cbm", "方": "cbm", "m³": "cbm", "m3": "cbm",
    "千克": "kg", "公斤": "kg", "KG": "kg", "Kg": "kg",
    "吨": "ton", "T": "ton", "t": "ton", "TON": "ton",
    "卷": "roll", "包": "bag", "箱": "box", "套": "set", "双": "pair",
}


def upgrade() -> None:
    # ① create units
    op.create_table(
        "units",
        sa.Column("code", sa.String(length=20), primary_key=True),
        sa.Column("label_i18n", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("code ~ '^[a-z0-9_]+$'", name="ck_units_code_fmt"),
        sa.CheckConstraint("sort_order >= 0", name="ck_units_sort_nn"),
    )

    conn = op.get_bind()

    # ② 幂等 data-op seed
    for code, label_i18n, sort_order in _UNIT_SEEDS:
        conn.execute(sa.text(
            "INSERT INTO units (code, label_i18n, sort_order, is_active, created_at, updated_at) "
            "VALUES (:code, CAST(:label_i18n AS JSONB), :sort_order, true, now(), now()) "
            "ON CONFLICT (code) DO NOTHING"
        ), {"code": code, "label_i18n": __import__("json").dumps(label_i18n), "sort_order": sort_order})

    # ③ 回填 sku.unit 自由文本 → code
    existing = {r[0] for r in conn.execute(sa.text("SELECT DISTINCT unit FROM skus"))}
    unmapped = sorted(v for v in existing if v not in _UNIT_BACKFILL)
    if unmapped:
        raise RuntimeError(
            f"0012 迁移中止:skus.unit 存在无法映射到 units.code 的历史取值 {unmapped!r}"
            "——请在 _UNIT_BACKFILL 补齐映射后重跑迁移(禁止静默丢弃/猜测映射)"
        )
    for raw, code in _UNIT_BACKFILL.items():
        if raw == code:
            continue  # 已是合法 code,免更新
        conn.execute(sa.text("UPDATE skus SET unit = :code WHERE unit = :raw"),
                     {"code": code, "raw": raw})

    # ④ 加 FK + 索引(最后加,确保数据已全部合法)
    op.create_foreign_key(
        "fk_skus_unit_units", "skus", "units", ["unit"], ["code"], ondelete="RESTRICT")
    op.create_index("ix_skus_unit", "skus", ["unit"])


def downgrade() -> None:
    op.drop_index("ix_skus_unit", table_name="skus")
    op.drop_constraint("fk_skus_unit_units", "skus", type_="foreignkey")
    op.drop_table("units")
    # sku.unit 类型全程未变(自始至终 String(20)),FK/索引已移除即完成退回;
    # 不反译 code → 历史原文(不可知,code 本身是合法 String,留原地)。
