from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin, SoftDeleteMixin


class SpuStatus:
    """商品生命周期状态机(单一源头)。

    语义按内部履约正名:管的是「能否被下游(报价)选用」,不是电商的对外可见/上架。
    - DRAFT    草稿:新建默认,录入中,不可被报价选用。可编辑、可删。
    - ACTIVE   启用:完备(有带价在售 SKU),可被报价选用。**不可编辑**(先停用再改)。
    - INACTIVE 停用:曾启用现下线/淘汰,不可被新报价选用,留历史。可编辑、可删、可重启用。

    转移矩阵 / 可编辑集 / 可删集三张表集中在此,service 每个写入口据此守卫,
    前端把它镜像成按钮显隐 —— 不散落 if/else,不并列两份(见 CLAUDE.md 设计决策方法论)。
    """
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"

    ALL = (DRAFT, ACTIVE, INACTIVE)

    # 合法转移白名单:启用/停用两向 + 停用后可重启;DRAFT 只进不回(启用过不回草稿)。
    TRANSITIONS = {
        DRAFT: (ACTIVE,),
        ACTIVE: (INACTIVE,),
        INACTIVE: (ACTIVE,),
    }
    EDITABLE = (DRAFT, INACTIVE)   # ACTIVE 锁编辑,先停用再改
    DELETABLE = (DRAFT, INACTIVE)

    @classmethod
    def can_transition(cls, current: str, target: str) -> bool:
        return target in cls.TRANSITIONS.get(current, ())


class Spu(Base, TimestampUpdateMixin, SoftDeleteMixin):
    __tablename__ = "spus"
    __table_args__ = (
        # 品类子树前缀过滤(list_spus 里 category_code LIKE '前缀.%')走索引:本库 locale
        # 非 C,btree 默认 opclass 不支持前缀 LIKE 索引扫描,需 text_pattern_ops 专用索引。
        # 模型在此声明 = 迁移创建 = create_all 建表,三者单一源头,不再靠迁移单方面偷偷加。
        Index("ix_spus_category_code_prefix", "category_code",
              postgresql_ops={"category_code": "text_pattern_ops"}),
        # SPU 维度搜索:pg_trgm GIN 加速 search_text ILIKE(名+品牌+产品级规格),同 skus。
        Index("ix_spus_search_text_trgm", "search_text",
              postgresql_using="gin", postgresql_ops={"search_text": "gin_trgm_ops"}),
        # 状态 DB 兜底(纵深防御,与 category_spec_attributes 的 value_type/source CHECK 同纪律)
        CheckConstraint("status IN ('DRAFT','ACTIVE','INACTIVE')", name="ck_spus_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spu_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    # ON DELETE RESTRICT 显式:品类被引用时不可硬删(同 sku.unit 口径;categories 实际只软删)
    category_code: Mapped[str] = mapped_column(
        String(50), ForeignKey("categories.code", ondelete="RESTRICT"), nullable=False, index=True)
    name_i18n: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # 主数据补全(商品概念层,跨 SKU 变体一致):
    #   brand 可选品牌文本(值非枚举,可中文;不同品牌本就拆成不同 SPU,故一 SPU 一品牌);
    #   description 中性商品描述(≠红线内部备注);hs_code 海关归类(标准码,展示原样)。
    # 原产地不在此:来源侧属性(同一 SPU 不同供应商产地不同),归采购/批次/报关层。
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    hs_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 产品级规格值(scope='spu' 的属性),形状同 skus.spec_jsonb:[{key, value}, ...],
    # 只存 key+value(label/unit 回模板取)。SKU 完整规格 = 本列 ∪ sku.spec_jsonb(读时并集,
    # 不落库合并)。默认 [] 兼容既有行(见迁移 0013 server_default)。
    spec_jsonb: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # SPU 维度搜索文本(名+品牌+产品级规格,写路径重算,见 spu_service._spu_search_text)。
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=SpuStatus.DRAFT)
    # 图片已规范化到 product_images 表(封面=MAIN 行 / 轮播=GALLERY / 详情=DETAIL);此处不再挂图列。
    # 创建人(商品运营录入归属):一等业务字段,展示/筛"我的"/按人统计录入量直接用,
    # 故上行而非只走 audit_logs(见 base.py 审计归属约定)。FK RESTRICT + index。
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
