from __future__ import annotations

from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampUpdateMixin


class CustomsStatus:
    """报关派生状态(model 层常量,单一源头;纯派生零冗余列,前端镜像此值域)。
    展示走 i18n,存英文 code。口径见 customs_service.derive_status(唯一源头)。

    - NONE:无活动报关记录(未报关);
    - DECLARED:有活动记录、released_at 空(已申报);
    - RELEASED:有活动记录、released_at 非空(已放行)。

    海关驳回/退单不是第四态 —— 软删当前记录 + note 记因,重报 = 新记录。
    """
    NONE = "NONE"
    DECLARED = "DECLARED"
    RELEASED = "RELEASED"
    ALL = (NONE, DECLARED, RELEASED)


class CustomsDeclaration(Base, TimestampUpdateMixin, SoftDeleteMixin):
    """报关记录(发运柜子表,整柜一次报关,回填结果;非独立主单据)。

    报关行代办场景下的甲方留痕:报关单号 / 申报日期 / 放行日期 / 申报单位 / 口岸 / 备注。
    行级货物明细权威在报关行系统,不复刻。一柜至多一条**活动**记录(偏唯一);纠错口 =
    软删重录(同物流事件范式)。录入即「已申报」,不设待申报草稿态(未申报 = 无活动记录)。
    无红线字段(不含成本/采购价/供应商货值;申报货值不设结构化字段,留痕在扫描件内)。

    declaration_no = 海关外部报关单号(外部身份,内部不发号,不占 NumberScope)。
    """
    __tablename__ = "customs_declarations"
    __table_args__ = (
        # 放行日期不早于申报日期(同日快速通关合法)。DB 最强层兜底。
        CheckConstraint("released_at IS NULL OR released_at >= declared_at",
                        name="ck_customs_released_ge_declared"),
        # 每柜至多一条活动报关(偏唯一;软删行退出约束,可纠错重录)。镜像 uq_shipevents_arrived。
        Index("uq_customs_active_shipment", "shipment_order_id", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
        # 报关单号活动期唯一(防手滑重复录同一单号;软删行退出约束)。
        Index("uq_customs_active_declno", "declaration_no", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
        # FK 全量索引(偏唯一不算替代,列表派生 LEFT JOIN 走此索引)。
        Index("ix_customs_declarations_shipment", "shipment_order_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 挂柜。RESTRICT:被报关记录引用的柜不可硬删。
    shipment_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("shipment_orders.id", ondelete="RESTRICT"), nullable=False)
    # 海关报关单号(18 位实务留余量)。外部身份,非本系统发号。
    declaration_no: Mapped[str] = mapped_column(String(32), nullable=False)
    # 申报日期(Date 粒度,与柜船期 etd/eta/atd 同粒度)。
    declared_at: Mapped[date] = mapped_column(Date, nullable=False)
    # 放行日期,回填(空 = 已申报未放行)。
    released_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 申报单位(报关单权威栏名:向海关递单的报关企业,覆盖报关行/货代代办/自营)/ 口岸,
    # 均自由文本(受控值域框架:唯一消费者=展示,无按申报单位聚合/结算需求)。
    declarant: Mapped[str | None] = mapped_column(String(100), nullable=True)
    customs_office: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 备注(查验等异常过程记这里)。
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 录入人(审计归属);改/删动作走 audit_logs,不加 updated_by。
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
