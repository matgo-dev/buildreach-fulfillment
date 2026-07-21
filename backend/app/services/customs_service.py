"""报关记录服务(发运柜子资源)。整柜一次报关,回填结果,软删重录纠错。

锁序(TOCTOU 闭合):录/改/删一律先锁柜头 FOR UPDATE(复用 get_order_for_update)再校验柜态
{LOADED, DEPARTED} —— 与「撤封柜前置无活动报关」串行化。柜头恒为叶子锁,锁后只碰报关/附件行。

报关状态纯派生(derive_status,唯一口径),不落柜头/记录冗余状态列。无红线字段。
一柜至多一条活动记录:柜头锁使「无活动」预检可靠(返回友好 42013),DB 偏唯一为并发漏网兜底。
PATCH 带乐观锁 + 显式 bump updated_at(附件集变更也须让基线前移,防 stale 覆盖)。
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.exceptions import (
    CustomsDuplicateActiveError,
    CustomsEditConflictError,
    CustomsNotOnShipmentError,
    CustomsShipmentNotDeclarableError,
    NotFoundError,
    ValidationFailedError,
)
from app.db.models.customs_declaration import CustomsDeclaration, CustomsStatus
from app.db.models.shipment_order import ShipmentOrder, ShipmentOrderStatus
from app.services import attachment_service, shipment_service
from app.services.repo import assert_no_edit_conflict

# 可报关的柜态:封柜后、报关行代办期间(离港前后皆可回填放行)。
_DECLARABLE_STATUSES = frozenset({ShipmentOrderStatus.LOADED, ShipmentOrderStatus.DEPARTED})
# 稀疏 PATCH 可写字段(全量覆盖式)。
_EDITABLE_FIELDS = ("declaration_no", "declared_at", "released_at", "declarant",
                    "customs_office", "note")
_NON_NULLABLE = ("declaration_no", "declared_at")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _assert_released_ge_declared(declared_at: date | None, released_at: date | None) -> None:
    """放行日不早于申报日(service 给友好 400;DB CHECK ck_customs_released_ge_declared 兜底并发/漏网)。"""
    if declared_at is not None and released_at is not None and released_at < declared_at:
        raise ValidationFailedError("放行日期不得早于申报日期")


def derive_status(decl: CustomsDeclaration | None) -> str:
    """报关状态唯一派生口径:无活动记录 → NONE;有记录 released_at 空 → DECLARED;非空 → RELEASED。"""
    if decl is None:
        return CustomsStatus.NONE
    return CustomsStatus.DECLARED if decl.released_at is None else CustomsStatus.RELEASED


def derive_list_status(ship_status: str, decl: CustomsDeclaration | None) -> str | None:
    """列表/详情派生列口径:柜非 LOADED/DEPARTED(OPEN/CANCELLED)→ None(前端显「—」);
    否则按活动记录派生 NONE/DECLARED/RELEASED。与 list_orders 的报关筛选三分支同口径。"""
    if ship_status not in _DECLARABLE_STATUSES:
        return None
    return derive_status(decl)


async def get_active(db: AsyncSession, shipment_id: int) -> CustomsDeclaration | None:
    """取某柜活动报关记录(至多一条,偏唯一保证)。详情/列表派生用。"""
    return (await db.execute(select(CustomsDeclaration).where(
        CustomsDeclaration.shipment_order_id == shipment_id,
        CustomsDeclaration.deleted_at.is_(None)))).scalar_one_or_none()


async def _lock_declarable_shipment(db: AsyncSession, shipment_id: int) -> ShipmentOrder:
    """锁柜头(FOR UPDATE)+ 校验柜态 ∈ {LOADED, DEPARTED}。录/改/删的统一前置。"""
    ship = await shipment_service.get_order_for_update(db, shipment_id)
    if ship.status not in _DECLARABLE_STATUSES:
        raise CustomsShipmentNotDeclarableError()
    return ship


async def _get_active_decl(db: AsyncSession, shipment_id: int,
                           decl_id: int) -> CustomsDeclaration:
    """取活动报关记录;不存在/已删 → 404;存在但不属于该柜 → 42014(仅跨柜语义)。"""
    decl = (await db.execute(select(CustomsDeclaration).where(
        CustomsDeclaration.id == decl_id,
        CustomsDeclaration.deleted_at.is_(None)))).scalar_one_or_none()
    if decl is None:
        raise NotFoundError(f"报关记录不存在: {decl_id}")
    if decl.shipment_order_id != shipment_id:
        raise CustomsNotOnShipmentError()
    return decl


async def create(db: AsyncSession, *, shipment_id: int, fields: dict,
                 attachment_ids: list[int], actor_user_id, actor_user_email,
                 request: Request | None = None) -> CustomsDeclaration:
    """录入报关。管线:锁柜头 → 柜态 → 无活动记录(42013)→ 建 → 关联附件 → 审计。"""
    await _lock_declarable_shipment(db, shipment_id)
    if await get_active(db, shipment_id) is not None:
        raise CustomsDuplicateActiveError()
    _assert_released_ge_declared(fields.get("declared_at"), fields.get("released_at"))
    decl = CustomsDeclaration(
        shipment_order_id=shipment_id, created_by=actor_user_id,
        **{k: fields.get(k) for k in _EDITABLE_FIELDS})
    db.add(decl)
    await db.flush()
    if attachment_ids:
        await attachment_service.sync_attachments(
            db, user_id=actor_user_id, declaration_id=decl.id, attachment_ids=attachment_ids)
    await write_audit(db, resource_type=AuditResourceType.CUSTOMS_DECLARATION,
                      action=AuditAction.CREATE, user_id=actor_user_id,
                      user_email=actor_user_email, resource_id=decl.id, request=request,
                      extra={"shipment_id": shipment_id}, commit=False)
    await db.commit()
    await db.refresh(decl)
    return decl


async def update(db: AsyncSession, *, shipment_id: int, decl_id: int, fields: dict,
                 attachment_ids: list[int] | None, expected_updated_at,
                 actor_user_id, actor_user_email,
                 request: Request | None = None) -> CustomsDeclaration:
    """改报关(稀疏 PATCH + 乐观锁 + 回填放行 + 全量替换附件)。
    管线:锁柜头 → 柜态 → 取活动记录+归属 → 乐观锁 → 覆盖字段 → 同步附件 → 显式 bump updated_at。
    declaration_no/declared_at 显式传 None 视为非法(NOT NULL)。attachment_ids=None 不动附件。"""
    await _lock_declarable_shipment(db, shipment_id)
    decl = await _get_active_decl(db, shipment_id, decl_id)
    assert_no_edit_conflict(decl, expected_updated_at, CustomsEditConflictError)
    for name in _EDITABLE_FIELDS:
        if name in fields:
            if name in _NON_NULLABLE and fields[name] is None:
                raise ValidationFailedError(f"{name} 不可置空")
            setattr(decl, name, fields[name])
    _assert_released_ge_declared(decl.declared_at, decl.released_at)
    removed: list[int] = []
    if attachment_ids is not None:
        removed = await attachment_service.sync_attachments(
            db, user_id=actor_user_id, declaration_id=decl.id, attachment_ids=attachment_ids)
    # 显式 bump:仅附件集变更(不写报关行字段)时,onupdate 不触发,基线不前移会让并发
    # stale 提交漏过乐观锁。故无条件前移 updated_at。
    decl.updated_at = _now()
    await db.flush()
    extra: dict = {"shipment_id": shipment_id}
    if removed:
        extra["removed_attachment_ids"] = removed
    await write_audit(db, resource_type=AuditResourceType.CUSTOMS_DECLARATION,
                      action=AuditAction.UPDATE, user_id=actor_user_id,
                      user_email=actor_user_email, resource_id=decl.id, request=request,
                      extra=extra, commit=False)
    await db.commit()
    await db.refresh(decl)
    return decl


async def delete(db: AsyncSession, *, shipment_id: int, decl_id: int, actor_user_id,
                 actor_user_email, request: Request | None = None) -> None:
    """软删报关(纠错重录),级联软删其附件。extra 带被删附件 id + 记录快照,供精确追溯。"""
    await _lock_declarable_shipment(db, shipment_id)
    decl = await _get_active_decl(db, shipment_id, decl_id)
    removed = await attachment_service.cascade_soft_delete(db, decl.id)
    snapshot = {"declaration_no": decl.declaration_no,
                "declared_at": decl.declared_at.isoformat(),
                "released_at": decl.released_at.isoformat() if decl.released_at else None}
    decl.deleted_at = datetime.now(timezone.utc)
    await write_audit(db, resource_type=AuditResourceType.CUSTOMS_DECLARATION,
                      action=AuditAction.DELETE, user_id=actor_user_id,
                      user_email=actor_user_email, resource_id=decl.id, request=request,
                      extra={"shipment_id": shipment_id, "removed_attachment_ids": removed,
                             "snapshot": snapshot}, commit=False)
    await db.commit()


# ---------- 列表派生(批量,单条查走偏唯一索引,无 N+1)----------


async def active_by_shipments(db: AsyncSession,
                              shipment_ids: list[int]) -> dict[int, CustomsDeclaration]:
    """批量取各柜活动报关记录(列表派生列/筛选用)。偏唯一保证每柜至多一行,无放大。"""
    if not shipment_ids:
        return {}
    rows = (await db.execute(select(CustomsDeclaration).where(
        CustomsDeclaration.shipment_order_id.in_(shipment_ids),
        CustomsDeclaration.deleted_at.is_(None)))).scalars().all()
    return {d.shipment_order_id: d for d in rows}
