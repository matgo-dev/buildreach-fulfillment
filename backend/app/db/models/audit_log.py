from __future__ import annotations

from sqlalchemy import JSON, CheckConstraint, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AuditStatus:
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_resource_action", "resource_type", "action"),
        Index("ix_audit_created_at", "created_at"),
        Index("ix_audit_trace_id", "trace_id"),
        Index("ix_audit_user_id", "user_id"),
        # status 值域兜底(SUCCESS/FAILED,仅中间件写入)。
        CheckConstraint("status IN ('SUCCESS','FAILED')", name="ck_audit_logs_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # user_id 有意不设 FK:审计留痕独立于主体生命周期(行业常规),且 users 被全库 RESTRICT
    # 引用实际删不掉、孤儿风险≈0;查询用途仅按 user_id 过滤(已有 ix_audit_user_id 索引)。
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(50), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
