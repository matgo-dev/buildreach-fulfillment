"""报价草稿服务:建草稿(language 默认由客户偏好映射)+ 逐行录入带快照。"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import format_code
from app.core.exceptions import NotFoundError
from app.core.i18n import compose_spec_text, display
from app.core.languages import resolve_quote_language
from app.db.models.quotation import QuotationLine, QuotationOrder, QuotationStatus
from app.db.models.sku import Sku
from app.db.models.spu import Spu
from app.db.models.unit import Unit
from app.services import customer_service, spec_template_service as tmpl
from app.services.numbering import NumberScope, allocate


async def _next_quote_no(db: AsyncSession) -> str:
    # 单据号:Q{YYYYMM}{期内序号};按年月号段(编号服务)
    period = datetime.now(timezone.utc).strftime("%Y%m")
    seq = await allocate(db, NumberScope.QUOTATION, period)
    return format_code(NumberScope.QUOTATION, seq, period)


async def create_draft(db: AsyncSession, *, customer_id, currency, valid_until=None,
                       remark=None, actor_user_id, actor_user_email,
                       request: Request | None = None) -> QuotationOrder:
    customer = await customer_service.get_customer(db, customer_id)
    language = resolve_quote_language(customer.preferred_language)
    order = QuotationOrder(no=await _next_quote_no(db), customer_id=customer_id,
                           language=language, currency=currency, valid_until=valid_until,
                           status=QuotationStatus.DRAFT, created_by=actor_user_id, remark=remark)
    db.add(order)
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.QUOTATION, action=AuditAction.CREATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=order.id, request=request, commit=False)
    await db.commit()
    return order


async def get_order(db: AsyncSession, order_id: int) -> QuotationOrder:
    order = (await db.execute(
        select(QuotationOrder).where(QuotationOrder.id == order_id))).scalar_one_or_none()
    if order is None:
        raise NotFoundError(f"报价单不存在: {order_id}")
    return order


async def list_lines(db: AsyncSession, order_id: int) -> list[QuotationLine]:
    return list((await db.execute(
        select(QuotationLine).where(QuotationLine.quotation_order_id == order_id)
        .order_by(QuotationLine.sort_order))).scalars().all())


async def add_line(db: AsyncSession, *, order_id, sku_id, unit_price, qty, name_snapshot=None,
                   spec_text_snapshot=None, unit_snapshot=None, sort_order=0,
                   actor_user_id, actor_user_email, request: Request | None = None) -> QuotationLine:
    order = await get_order(db, order_id)
    sku = (await db.execute(select(Sku).where(Sku.id == sku_id))).scalar_one_or_none()
    if sku is None:
        raise NotFoundError(f"SKU 不存在: {sku_id}")
    spu = (await db.execute(select(Spu).where(Spu.id == sku.spu_id))).scalar_one()
    by_key = await tmpl.suggestions_by_key(db, spu.category_code)

    lang = order.language
    # 快照默认由 SKU + 模板按报价语言组合,均可被入参覆盖(线下定稿优先)
    name = name_snapshot if name_snapshot is not None else display(sku.name_i18n, lang)
    spec_text = (spec_text_snapshot if spec_text_snapshot is not None
                 else compose_spec_text(sku.spec_jsonb, by_key, lang))
    # unit_snapshot 冻结展示 label(镜像 name_snapshot=display(sku.name_i18n)):sku.unit
    # 是 units.code(身份/FK 列,不存中文),报价快照要历史保真——单位改名/停用后旧
    # 报价展示不变,故解析 code → units.label_i18n → display(..,lang) 冻结成文字,
    # 快照列本身零 join、无 FK(spec §11 Part A)。
    if unit_snapshot is not None:
        unit = unit_snapshot
    else:
        unit_row = (await db.execute(
            select(Unit).where(Unit.code == sku.unit))).scalar_one_or_none()
        unit = display(unit_row.label_i18n, lang) if unit_row is not None else sku.unit
    total = Decimal(str(unit_price)) * Decimal(str(qty))

    line = QuotationLine(quotation_order_id=order_id, sku_id=sku_id, name_snapshot=name,
                         spec_text_snapshot=spec_text, unit_snapshot=unit,
                         unit_price=unit_price, qty=qty, line_total=total,
                         language=lang, sort_order=sort_order)
    db.add(line)
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.QUOTATION, action=AuditAction.UPDATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=order_id, request=request, commit=False)
    await db.commit()
    return line
