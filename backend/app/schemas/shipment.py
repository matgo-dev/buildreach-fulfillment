"""发运单(=柜)schemas。本步最小骨架:柜号/柜型/封条/备注。无红线字段。

柜型 = 应用层受控值域(20GP/40GP/40HQ/45HQ),单一源头在此(前端镜像),不落 DB CHECK
(受控值域框架:消费者仅表单校验)。船务字段/装船态归发运步扩展。
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator

# 柜型受控值域单一源头(应用层枚举,前端镜像;加柜型 = 加一条,别在别处再列一份)。
CONTAINER_TYPES = ("20GP", "40GP", "40HQ", "45HQ")


class _ShipmentWriteBase(BaseModel):
    container_no: str | None = None
    container_type: str | None = None
    seal_no: str | None = None
    note: str | None = None

    @field_validator("container_type")
    @classmethod
    def _validate_container_type(cls, v: str | None) -> str | None:
        if v is not None and v not in CONTAINER_TYPES:
            raise ValueError(f"柜型须是 {CONTAINER_TYPES} 之一")
        return v


class ShipmentCreateIn(_ShipmentWriteBase):
    """建柜(组柜中 OPEN)。柜号组柜期可空。"""


class ShipmentUpdateIn(_ShipmentWriteBase):
    """改柜(仅 OPEN):柜号/柜型/封条/备注整体重写。"""


class ShipmentOut(BaseModel):
    id: int
    no: str
    container_no: str | None
    container_type: str | None
    seal_no: str | None
    note: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, ship, extra: dict | None = None) -> dict:
        d = cls.model_validate(ship, from_attributes=True).model_dump()
        if extra:
            d.update(extra)
        return d


class ShipmentListItem(BaseModel):
    id: int
    no: str
    container_no: str | None
    container_type: str | None
    seal_no: str | None
    status: str
    outbound_count: int
    created_at: datetime
