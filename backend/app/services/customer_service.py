"""客户 service(建/列/取/改/启停,照 suppliers 档次)。"""
from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import NumberScope, format_code
from app.core.exceptions import NotFoundError
from app.db.models.customer import Customer, CustomerStatus
from app.services.numbering import allocate
from app.services.repo import get_or_404, paginate


async def create_customer(db: AsyncSession, *, name, quote_language=None,
                          contact_name=None, contact_phone=None, contact_email=None,
                          address=None, actor_user_id, actor_user_email,
                          request: Request | None = None) -> Customer:
    code = format_code(NumberScope.CUSTOMER, await allocate(db, NumberScope.CUSTOMER))
    customer = Customer(
        code=code, name=name,
        quote_language=quote_language, contact_name=contact_name,
        contact_phone=contact_phone, contact_email=contact_email, address=address)
    db.add(customer)
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.CUSTOMER,
                      action=AuditAction.CREATE, user_id=actor_user_id,
                      user_email=actor_user_email, resource_id=customer.id,
                      request=request, commit=False)
    await db.commit()
    return customer


async def list_customers(db: AsyncSession, *, status=None, keyword=None,
                         page: int = 1, size: int = 20) -> tuple[list[Customer], int]:
    """列表:筛选(状态/关键词 code|name|联系人)+ 分页,updated_at 降序(镜像 suppliers)。"""
    conds = []
    if status:
        conds.append(Customer.status == status)
    if keyword:
        like = f"%{keyword}%"
        conds.append(or_(Customer.code.ilike(like), Customer.name.ilike(like),
                         Customer.contact_name.ilike(like)))
    return await paginate(
        db, select(Customer).where(*conds).order_by(Customer.updated_at.desc()),
        page=page, size=size, count_stmt=select(func.count(Customer.id)).where(*conds))


async def get_customer(db: AsyncSession, customer_id: int) -> Customer:
    return await get_or_404(db, Customer, customer_id,
                            error_cls=NotFoundError, message="客户不存在")


async def update_customer(db: AsyncSession, *, customer_id, name, quote_language=None,
                          contact_name=None, contact_phone=None, contact_email=None,
                          address=None, actor_user_id, actor_user_email,
                          request: Request | None = None) -> Customer:
    c = await get_customer(db, customer_id)
    c.name = name
    c.quote_language = quote_language
    c.contact_name, c.contact_phone = contact_name, contact_phone
    c.contact_email, c.address = contact_email, address
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.CUSTOMER, action=AuditAction.UPDATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=c.id, request=request, commit=False)
    await db.commit()
    await db.refresh(c)
    return c


async def set_status(db: AsyncSession, *, customer_id, target: str, actor_user_id,
                     actor_user_email, request: Request | None = None) -> Customer:
    """启停切换(ACTIVE↔INACTIVE)。幂等:已是目标态直接返回(不写多余审计)。"""
    c = await get_customer(db, customer_id)
    if c.status == target:
        return c
    c.status = target
    action = (AuditAction.ACTIVATE if target == CustomerStatus.ACTIVE
              else AuditAction.DEACTIVATE)
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.CUSTOMER, action=action,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=c.id, request=request, commit=False)
    await db.commit()
    await db.refresh(c)
    return c
