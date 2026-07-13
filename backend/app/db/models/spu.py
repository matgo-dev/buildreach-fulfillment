from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
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
        # 状态 DB 兜底(纵深防御,与 category_spec_attributes 的 value_type/source CHECK 同纪律)
        CheckConstraint("status IN ('DRAFT','ACTIVE','INACTIVE')", name="ck_spus_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spu_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    # ON DELETE RESTRICT 显式:品类被引用时不可硬删(同 sku.unit 口径;categories 实际只软删)
    category_code: Mapped[str] = mapped_column(
        String(50), ForeignKey("categories.code", ondelete="RESTRICT"), nullable=False, index=True)
    name_i18n: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=SpuStatus.DRAFT)
    # 图片已规范化到 product_images 表(封面=MAIN 行 / 轮播=GALLERY / 详情=DETAIL);此处不再挂图列。
    # 创建人(商品运营录入归属):一等业务字段,展示/筛"我的"/按人统计录入量直接用,
    # 故上行而非只走 audit_logs(见 base.py 审计归属约定)。FK RESTRICT + index。
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
