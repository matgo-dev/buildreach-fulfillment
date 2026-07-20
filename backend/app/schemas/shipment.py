"""发运单(=柜)schemas。组柜容器 + 船务生命周期(装柜/离港)。无红线字段(成本/供应商/售价)。

柜型 = 应用层受控值域(20GP/40GP/40HQ/45HQ),单一源头在此(前端镜像),不落 DB CHECK。
船务字段全可选(逐步补录);编辑门禁(哪个字段在哪个状态可改)权威源在
model 层 SHIPMENT_EDITABLE_FIELDS_BY_STATUS,service diff 式比对,schema 不重复门禁语义。
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

# 柜型受控值域单一源头(应用层枚举,前端镜像;加柜型 = 加一条,别在别处再列一份)。
CONTAINER_TYPES = ("20GP", "40GP", "40HQ", "45HQ")


class _ShipmentWriteBase(BaseModel):
    """建柜 / 改柜共用字段(全量覆盖式;save 侧按状态 diff 门禁)。atd 不在此——
    它由离港确认动作驱动,不走整单保存。"""
    container_no: str | None = Field(default=None, max_length=20)
    container_type: str | None = None
    seal_no: str | None = Field(default=None, max_length=30)
    note: str | None = None
    booking_no: str | None = Field(default=None, max_length=30)
    vessel_name: str | None = Field(default=None, max_length=60)
    voyage_no: str | None = Field(default=None, max_length=20)
    bl_no: str | None = Field(default=None, max_length=40)
    port_of_loading: str | None = Field(default=None, max_length=60)
    port_of_discharge: str | None = Field(default=None, max_length=60)
    etd: date | None = None
    eta: date | None = None

    @field_validator("container_type")
    @classmethod
    def _validate_container_type(cls, v: str | None) -> str | None:
        if v is not None and v not in CONTAINER_TYPES:
            raise ValueError(f"柜型须是 {CONTAINER_TYPES} 之一")
        return v


class ShipmentCreateIn(_ShipmentWriteBase):
    """建柜(组柜中 OPEN)。柜号组柜期可空;船务字段建柜即录(可选)。"""


class ShipmentUpdateIn(_ShipmentWriteBase):
    """改柜(稀疏 PATCH):仅传入字段参与门禁 + 覆盖(未传字段不动)。
    乐观锁基线**必填**(对齐入库/出库/报价/采购先例:不许有的有有的没有);漏传 → 422。"""
    expected_updated_at: datetime


class ShipmentLoadIn(BaseModel):
    """装柜确认(OPEN→LOADED)。可带 seal_no/container_no 补录(封号贴封条时才知道)。"""
    container_no: str | None = Field(default=None, max_length=20)
    seal_no: str | None = Field(default=None, max_length=30)


class ShipmentDepartIn(BaseModel):
    """离港确认(LOADED→DEPARTED)。atd 实际离港日,缺省 = 当日。"""
    atd: date | None = None


class ShipmentOut(BaseModel):
    id: int
    no: str
    container_no: str | None
    container_type: str | None
    seal_no: str | None
    note: str | None
    booking_no: str | None
    vessel_name: str | None
    voyage_no: str | None
    bl_no: str | None
    port_of_loading: str | None
    port_of_discharge: str | None
    etd: date | None
    eta: date | None
    atd: date | None
    loaded_at: datetime | None
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
    vessel_name: str | None
    voyage_no: str | None
    etd: date | None
    atd: date | None
    status: str
    outbound_count: int
    created_at: datetime
