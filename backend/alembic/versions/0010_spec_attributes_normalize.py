"""spec attributes normalize: category_spec_suggestions(JSONB 数组) → category_spec_attributes(一属性一行)

Revision ID: 0010_spec_attributes_normalize
Revises: 0009_catalog_images

M1 回补(category_spec_suggestions 是 M1 建的):旧模型一分类一行 + suggestions
JSONB 数组,存在 read-modify-write 丢更新(两人同类目各加一属性互相覆盖)+ key
唯一性无 DB 约束两个问题。本迁移展开成一属性一行,DB 层 UNIQUE(category_code,key)
硬保证唯一性。

upgrade 时序(写死,不走 autogenerate):
  ① create category_spec_attributes(含 UNIQUE + 4 个 CHECK)。运营新增属性的稳定
     key 由应用层生成独立随机 token(a_<8位 base62>,见 app/services/
     spec_template_service.create_new_attribute),插入前生成、一次 INSERT、不回填、
     不派生自 id,唯一性靠本迁移建的 UNIQUE(category_code,key) 兜底——迁移本身不需要
     额外的 DB 对象(不建 sequence)。
  ② 从旧表逐行读 suggestions 数组,展开前查 (category_code, key) 重复 → 有则 raise(fail,
     不静默取一条;要求人工先去重旧数据)
  ③ 逐行 INSERT 新表
  ④ 数据搬完确认后 drop 旧表 category_spec_suggestions(同一迁移内、搬完再 drop)

downgrade 有损,已明写:按 category_code 把新表多行重新聚合回旧结构的 JSONB 数组;
enum 属性的 options(新表独有,旧结构从未支持)在回退中丢失 —— 若曾在 0010 之后
新增过 enum 候选值,降级前需业务确认可接受丢失,或改走数据导出另存。
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_spec_attributes_normalize"
down_revision = "0009_catalog_images"
branch_labels = None
depends_on = None

# 旧 source 机器化:种子/运营手加(中文,反模式)→ seed/operator(机器键)。
_SOURCE_FORWARD = {
    "种子": "seed", "运营手加": "operator",
    "seed": "seed", "operator": "operator",  # 幂等:若已是机器键原样放行
}
_SOURCE_BACKWARD = {"seed": "种子", "operator": "运营手加"}


def upgrade() -> None:
    # ① create 新表
    op.create_table(
        "category_spec_attributes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("category_code", sa.String(length=50), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("label_i18n", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("value_type", sa.String(length=20), nullable=False, server_default="string"),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text(), none_as_null=True), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["category_code"], ["categories.code"]),
        sa.UniqueConstraint("category_code", "key", name="uq_cat_spec_attr_cat_key"),
        sa.CheckConstraint(
            "value_type IN ('string','number','enum')", name="ck_cat_spec_attr_value_type"),
        sa.CheckConstraint("source IN ('seed','operator')", name="ck_cat_spec_attr_source"),
        sa.CheckConstraint("sort_order >= 0", name="ck_cat_spec_attr_sort_nn"),
        sa.CheckConstraint(
            "(value_type = 'enum') = (options IS NOT NULL)",
            name="ck_cat_spec_attr_options_iff_enum"),
    )

    conn = op.get_bind()
    old_rows = conn.execute(sa.text(
        "SELECT category_code, suggestions FROM category_spec_suggestions"
    )).fetchall()

    # ② 展开前查 (category_code, key) 重复 → 有则 raise
    seen: set[tuple[str, str]] = set()
    to_insert: list[dict] = []
    for category_code, suggestions in old_rows:
        suggestions = suggestions if isinstance(suggestions, list) else json.loads(suggestions)
        for item in suggestions:
            key = item["key"]
            dup = (category_code, key)
            if dup in seen:
                raise RuntimeError(
                    f"0010 迁移中止:分类 {category_code!r} 下重复 key={key!r}"
                    "(旧 category_spec_suggestions 同分类同 key 出现多次,需人工先去重再迁移)"
                )
            seen.add(dup)

            source_raw = item.get("source")
            source = _SOURCE_FORWARD.get(source_raw)
            if source is None:
                raise RuntimeError(
                    f"0010 迁移中止:分类 {category_code!r} key={key!r} 的 source={source_raw!r} "
                    "非法(仅接受 种子/运营手加/seed/operator)"
                )

            value_type = item.get("value_type") or "string"
            options = item.get("options")
            if value_type == "enum" and not options:
                # 旧结构从未支持 options 字段;缺 options 的 enum 项无法满足新 CHECK
                # (value_type='enum') = (options IS NOT NULL)。不编造候选值,降级为 string
                # ——字面值仍原样保留在 SKU 侧,只是模板不再声称是可校验的 enum。
                value_type = "string"

            to_insert.append({
                "category_code": category_code,
                "key": key,
                "label_i18n": json.dumps(item.get("label_i18n") or {}),
                "value_type": value_type,
                "options": json.dumps(options) if options else None,
                "unit": item.get("unit") or "",
                "sort_order": item.get("sort_order", 0),
                "source": source,
            })

    # ③ 逐行 INSERT 新表
    for row in to_insert:
        conn.execute(sa.text(
            "INSERT INTO category_spec_attributes "
            "(category_code, key, label_i18n, value_type, options, unit, sort_order, source, "
            " created_at, updated_at) "
            "VALUES (:category_code, :key, CAST(:label_i18n AS JSONB), :value_type, "
            " CAST(:options AS JSONB), :unit, :sort_order, :source, now(), now())"
        ), row)

    # ④ 数据搬完,drop 旧表
    op.drop_table("category_spec_suggestions")


def downgrade() -> None:
    op.create_table(
        "category_spec_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("category_code", sa.String(length=50), nullable=False),
        sa.Column("suggestions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["category_code"], ["categories.code"]),
    )
    op.create_index(
        "ix_category_spec_suggestions_category_code", "category_spec_suggestions",
        ["category_code"], unique=True)

    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT category_code, key, label_i18n, value_type, unit, sort_order, source "
        "FROM category_spec_attributes ORDER BY category_code, sort_order, id"
    )).fetchall()

    grouped: dict[str, list[dict]] = {}
    for category_code, key, label_i18n, value_type, unit, sort_order, source in rows:
        label_i18n = label_i18n if isinstance(label_i18n, dict) else json.loads(label_i18n)
        grouped.setdefault(category_code, []).append({
            "key": key,
            "label_i18n": label_i18n,
            "value_type": value_type,
            "unit": unit,
            "sort_order": sort_order,
            # enum 的 options 在此丢失(旧结构无承载),仅当时机器键回译成旧中文值,
            # 与旧 SuggestionSource 常量对齐。
            "source": _SOURCE_BACKWARD.get(source, source),
        })

    for category_code, suggestions in grouped.items():
        conn.execute(sa.text(
            "INSERT INTO category_spec_suggestions (category_code, suggestions, created_at, updated_at) "
            "VALUES (:category_code, CAST(:suggestions AS JSONB), now(), now())"
        ), {"category_code": category_code, "suggestions": json.dumps(suggestions)})

    op.drop_table("category_spec_attributes")
