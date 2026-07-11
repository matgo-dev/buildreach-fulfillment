from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class SuggestionSource:
    """机器键(禁中文,身份≠展示;中文标签走前端 i18n)。"""
    SEED = "seed"
    OPERATOR = "operator"


class CategorySpecAttribute(Base, TimestampUpdateMixin):
    """分类规格属性模板 —— 一属性一行(正规化)。

    key 为稳定 ASCII 键(身份,SKU spec_jsonb 引用它):
    种子属性给有意义键(material/diameter);运营手输新属性由后端生成独立随机稳定键
    `a_<8位 base62>`(见 spec_template_service.create_new_attribute)——绝不取中文
    原文当键、绝不翻译。一属性一行(而非分类挂一个 JSONB 数组):不同属性各自一行、
    并发编辑互不覆盖,UNIQUE(category_code, key) 由 DB 硬保唯一。

    audit 列沿用 TimestampUpdateMixin(不加 created_by)——主数据操作者追溯走 audit_log,
    对齐全仓口径(唯 quotation 交易域带 created_by)。
    """
    __tablename__ = "category_spec_attributes"
    __table_args__ = (
        UniqueConstraint("category_code", "key", name="uq_cat_spec_attr_cat_key"),
        CheckConstraint(
            "value_type IN ('string','number','enum')", name="ck_cat_spec_attr_value_type"),
        CheckConstraint("source IN ('seed','operator')", name="ck_cat_spec_attr_source"),
        CheckConstraint("sort_order >= 0", name="ck_cat_spec_attr_sort_nn"),
        CheckConstraint(
            "(value_type = 'enum') = (options IS NOT NULL)",
            name="ck_cat_spec_attr_options_iff_enum"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 不另建 INDEX(category_code):UNIQUE(category_code,key) 的最左前缀已覆盖该查询路径。
    # ON DELETE RESTRICT 显式:品类被规格模板引用时不可硬删(同 sku.unit 口径)
    category_code: Mapped[str] = mapped_column(
        String(50), ForeignKey("categories.code", ondelete="RESTRICT"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    label_i18n: Mapped[dict] = mapped_column(JSONB, nullable=False)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False, default="string")
    # enum 候选值:[{"code": "...", "label_i18n": {...}}, ...];非 enum 恒为 NULL(见 CHECK)。
    # none_as_null=True:Python None → SQL NULL(而非 JSONB 'null' 字面量),否则
    # ck_cat_spec_attr_options_iff_enum 会把 'null'::jsonb 误判成"非空"而报违反 CHECK。
    options: Mapped[list | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
