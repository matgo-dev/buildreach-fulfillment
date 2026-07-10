"""客户 service(最小档:建 + 列 + 取)。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import format_customer_code
from app.core.exceptions import NotFoundError
from app.db.models.customer import Customer
from app.services.numbering import NumberScope, allocate


async def create_customer(db: AsyncSession, *, name_i18n, preferred_language=None,
                          contact_name=None, contact_phone=None, contact_email=None,
                          address=None, actor_user_id, actor_user_email,
                          request: Request | None = None) -> Customer:
    code = format_customer_code(await allocate(db, NumberScope.CUSTOMER))
    customer = Customer(
        code=code, name_i18n=name_i18n,
        preferred_language=preferred_language, contact_name=contact_name,
        contact_phone=contact_phone, contact_email=contact_email, address=address)
    db.add(customer)
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.CUSTOMER,
                      action=AuditAction.CREATE, user_id=actor_user_id,
                      user_email=actor_user_email, resource_id=customer.id,
                      request=request, commit=False)
    await db.commit()
    return customer


async def list_customers(db: AsyncSession) -> list[Customer]:
    return list((await db.execute(select(Customer))).scalars().all())


async def get_customer(db: AsyncSession, customer_id: int) -> Customer:
    c = (await db.execute(
        select(Customer).where(Customer.id == customer_id))).scalar_one_or_none()
    if c is None:
        raise NotFoundError("客户不存在")
    return c
