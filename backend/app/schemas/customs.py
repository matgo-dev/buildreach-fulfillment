"""报关记录 schemas(发运柜子资源)。无红线字段(不含成本/采购价/供应商货值)。

customs_status 值域单一源头 = model 层 CustomsStatus;派生口径唯一源头 =
customs_service.derive_status。attachment_ids 全量替换语义(见 attachment_service.sync_attachments)。
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.attachment import AttachmentPublic


class CustomsDeclarationCreateIn(BaseModel):
    """录入报关(整柜一次)。declaration_no/declared_at 必填;released_at 可当场回填。
    attachment_ids 关联已上传的孤儿附件(可空)。"""
    declaration_no: str = Field(..., min_length=1, max_length=32)
    declared_at: date
    released_at: date | None = None
    declarant: str | None = Field(default=None, max_length=100)
    customs_office: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=500)
    attachment_ids: list[int] = Field(default_factory=list)


class CustomsDeclarationUpdateIn(BaseModel):
    """改报关(稀疏 PATCH,仅传入字段覆盖)+ 回填 released_at + 全量替换 attachment_ids。
    乐观锁基线**必填**(对齐柜/报价/采购先例;漏传 422),防 stale 界面覆盖他人改动 /
    静默软删同事刚挂的附件。attachment_ids 不传 = 不动附件;传了 = 全量替换(移出即软删)。
    declaration_no/declared_at 为 NOT NULL 列,传 null 非法(service 拒)。"""
    declaration_no: str | None = Field(default=None, min_length=1, max_length=32)
    declared_at: date | None = None
    released_at: date | None = None
    declarant: str | None = Field(default=None, max_length=100)
    customs_office: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=500)
    attachment_ids: list[int] | None = None
    expected_updated_at: datetime


class CustomsDeclarationOut(BaseModel):
    id: int
    shipment_order_id: int
    declaration_no: str
    declared_at: date
    released_at: date | None
    declarant: str | None
    customs_office: str | None
    note: str | None
    status: str          # 派生 customs_status(NONE 不会出现在实体上,活动记录必 DECLARED/RELEASED)
    attachments: list[AttachmentPublic]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, decl, *, status: str, attachments: list) -> dict:
        return cls(
            id=decl.id, shipment_order_id=decl.shipment_order_id,
            declaration_no=decl.declaration_no, declared_at=decl.declared_at,
            released_at=decl.released_at, declarant=decl.declarant,
            customs_office=decl.customs_office, note=decl.note, status=status,
            attachments=[AttachmentPublic.build(a) for a in attachments],
            created_at=decl.created_at, updated_at=decl.updated_at,
        ).model_dump()
