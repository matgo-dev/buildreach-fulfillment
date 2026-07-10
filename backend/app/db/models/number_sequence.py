from __future__ import annotations

from sqlalchemy import BigInteger, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NumberSequence(Base):
    """统一业务编号号段(编号服务的状态表)。

    scope=对象/单据类型(SKU/CUSTOMER/QUOTATION);period=号段分段键
    (主数据全局用 '';单据按年月 'YYYYMM')。next_seq=该号段已发出的最大序号。
    """
    __tablename__ = "number_sequences"
    __table_args__ = (UniqueConstraint("scope", "period", name="uq_number_scope_period"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(30), nullable=False)
    period: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    next_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
