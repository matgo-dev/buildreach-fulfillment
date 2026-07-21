"""物流轨迹事件 schemas(发运柜子资源)。无红线字段。

event_type 值域单一源头 = model 层 LogisticsMilestone.EVENT_TYPES(此处引用校验,不另列一份);
「已离港 DEPARTED」是派生态不入表,故不在可录入值域。当前物流状态纯派生,不落柜头冗余列。
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.db.models.shipment_event import LogisticsMilestone


def _validate_event_type(v: str | None) -> str | None:
    # None(PATCH 未传或不改)放行;非 None 必在可录入值域(引用 model 单一源头)。
    if v is not None and v not in LogisticsMilestone.EVENT_TYPES:
        raise ValueError(f"event_type must be one of {LogisticsMilestone.EVENT_TYPES}")
    return v


class ShipmentEventCreateIn(BaseModel):
    """录入在途里程碑(中转/到港)。event_type/event_at 必填;event_at 为事件业务日
    (service 另校验 ≥ 柜 atd)。"""
    event_type: str
    event_at: date
    location: str | None = Field(default=None, max_length=60)
    note: str | None = None

    _v_type = field_validator("event_type")(_validate_event_type)


class ShipmentEventUpdateIn(BaseModel):
    """纠错改事件(稀疏 PATCH,仅传入字段覆盖)。event_type 改为纠正误录节点用;
    不做乐观锁(事件行单操作者,并发靠录改删一律先锁柜头 FOR UPDATE 串行化)。"""
    event_type: str | None = None
    event_at: date | None = None
    location: str | None = Field(default=None, max_length=60)
    note: str | None = None

    _v_type = field_validator("event_type")(_validate_event_type)


class ShipmentEventOut(BaseModel):
    id: int
    event_type: str
    event_at: date
    location: str | None
    note: str | None
    created_at: datetime

    @classmethod
    def build(cls, ev) -> dict:
        return cls.model_validate(ev, from_attributes=True).model_dump()
