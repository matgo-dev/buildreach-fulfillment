"""商品图片规范化表 —— SPU 图与 SKU 图同表,靠 sku_id 区分层级。

设计:docs/superpowers/specs/2026-07-12-0514-商品图片建模-design.md(过独立 DB 评审)。
- 封面 = 该 SPU 唯一一行 image_type=MAIN(sku_id IS NULL);≤1 由部分唯一索引硬保证,≥1 由应用层。
- 身份键 = image_key(reconcile 按此对账),SPU 级 / SKU 级各一条部分唯一索引硬约束。
- 图片是内容非业务状态:走硬删(无 SoftDeleteMixin);谁上传的追溯走 audit_logs(不上 created_by,
  同 quotation_lines 组合子行口径,见 db/base.py 审计归属约定)。
"""
from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class ImageType:
    MAIN = "MAIN"        # 封面/主图(SPU 级唯一)
    GALLERY = "GALLERY"  # 轮播/主图组其余(SPU 级);SKU 级图一律记 GALLERY
    DETAIL = "DETAIL"    # 详情长图(SPU 级)
    ALL = (MAIN, GALLERY, DETAIL)


class ProductImage(Base, TimestampUpdateMixin):
    __tablename__ = "product_images"
    __table_args__ = (
        # 三态 code 值域 DB 兜底(纵深防御,同 spus.status / cat_spec_attr.value_type CHECK 纪律)
        CheckConstraint("image_type IN ('MAIN','GALLERY','DETAIL')", name="ck_product_images_type"),
        # 每 SPU 至多一张 SPU 级封面(≤1 DB 硬保证;≥1 应用层保证)
        Index("uq_product_images_spu_main", "spu_id", unique=True,
              postgresql_where=text("image_type = 'MAIN' AND sku_id IS NULL")),
        # 身份键硬约束(reconcile 按 image_key 对账,循 CategorySpecAttribute UNIQUE(category_code,key) 例)
        Index("uq_product_images_spu_key", "spu_id", "image_key", unique=True,
              postgresql_where=text("sku_id IS NULL")),
        Index("uq_product_images_sku_key", "sku_id", "image_key", unique=True,
              postgresql_where=text("sku_id IS NOT NULL")),
        # 查询路径:列 SPU 图按类型、列 SKU 图
        Index("ix_product_images_spu_type", "spu_id", "image_type"),
        Index("ix_product_images_sku", "sku_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 组合子行随父级硬删(与 0009 quotation_lines.order_id CASCADE 口径一致;实践中父级仅软删)
    spu_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("spus.id", ondelete="CASCADE"), nullable=False)
    sku_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("skus.id", ondelete="CASCADE"), nullable=True)
    image_key: Mapped[str] = mapped_column(String(255), nullable=False)
    image_type: Mapped[str] = mapped_column(String(20), nullable=False, default=ImageType.GALLERY)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
