"""供应商主数据服务(建/列/取/改/启停)。照 customers 档次,补 toggle(建 PO 需选 ACTIVE)。"""
from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import NumberScope, format_code
from app.core.exceptions import SupplierNotFoundError
from app.db.models.supplier import Supplier, SupplierStatus
from app.services.numbering import allocate


async def create_supplier(db: AsyncSession, *, name, default_currency=None, contact_name=None,
                          contact_phone=None, contact_email=None, address=None,
                          actor_user_id, actor_user_email, request: Request | None = None
                          ) -> Supplier:
    code = format_code(NumberScope.SUPPLIER, await allocate(db, NumberScope.SUPPLIER))
    supplier = Supplier(
        code=code, name=name, default_currency=default_currency, contact_name=contact_name,
        contact_phone=contact_phone, contact_email=contact_email, address=address,
        status=SupplierStatus.ACTIVE)
    db.add(supplier)
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.SUPPLIER, action=AuditAction.CREATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=supplier.id, request=request, commit=False)
    await db.commit()
    await db.refresh(supplier)
    return supplier


async def get_supplier(db: AsyncSession, supplier_id: int) -> Supplier:
    s = (await db.execute(
        select(Supplier).where(Supplier.id == supplier_id))).scalar_one_or_none()
    if s is None:
        raise SupplierNotFoundError(f"供应商不存在: {supplier_id}")
    return s


async def list_suppliers(db: AsyncSession, *, status=None, keyword=None,
                         page: int = 1, size: int = 20) -> tuple[list[Supplier], int]:
    """列表:筛选(状态/关键词 code|name|联系人)+ 分页,updated_at 降序。"""
    conds = []
    if status:
        conds.append(Supplier.status == status)
    if keyword:
        like = f"%{keyword}%"
        conds.append(or_(Supplier.code.ilike(like), Supplier.name.ilike(like),
                         Supplier.contact_name.ilike(like)))
    total = (await db.execute(
        select(func.count(Supplier.id)).where(*conds))).scalar_one()
    rows = list((await db.execute(
        select(Supplier).where(*conds).order_by(Supplier.updated_at.desc())
        .offset((page - 1) * size).limit(size))).scalars().all())
    return rows, total


async def update_supplier(db: AsyncSession, *, supplier_id, name, default_currency=None,
                          contact_name=None, contact_phone=None, contact_email=None,
                          address=None, actor_user_id, actor_user_email,
                          request: Request | None = None) -> Supplier:
    s = await get_supplier(db, supplier_id)
    s.name = name
    s.default_currency = default_currency
    s.contact_name, s.contact_phone = contact_name, contact_phone
    s.contact_email, s.address = contact_email, address
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.SUPPLIER, action=AuditAction.UPDATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=s.id, request=request, commit=False)
    await db.commit()
    await db.refresh(s)
    return s


async def set_status(db: AsyncSession, *, supplier_id, target: str, actor_user_id,
                     actor_user_email, request: Request | None = None) -> Supplier:
    """启停切换(ACTIVE↔INACTIVE)。幂等:已是目标态直接返回(不写多余审计)。"""
    s = await get_supplier(db, supplier_id)
    if s.status == target:
        return s
    s.status = target
    action = (AuditAction.ACTIVATE if target == SupplierStatus.ACTIVE
              else AuditAction.DEACTIVATE)
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.SUPPLIER, action=action,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=s.id, request=request, commit=False)
    await db.commit()
    await db.refresh(s)
    return s
