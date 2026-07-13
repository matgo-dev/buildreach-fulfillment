"""报价草稿服务:建草稿(language 默认由客户偏好映射)+ 逐行录入带快照。"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import NumberScope, format_code
from app.core.exceptions import (
    NotFoundError,
    QuotationEditConflictError,
    QuotationInvalidLineError,
    QuotationNotDraftError,
)
from app.core.i18n import compose_spec_text, display
from app.core.languages import DEFAULT_QUOTE_LANGUAGE
from app.db.models.quotation import (
    QUOTATION_EDITABLE,
    QuotationLine,
    QuotationOrder,
    QuotationStatus,
)
from app.db.models.sku import Sku
from app.db.models.spu import Spu
from app.db.models.unit import Unit
from app.services import customer_service, sku_service, spec_template_service as tmpl
from app.services.numbering import allocate


async def compose_line_snapshot(db: AsyncSession, sku: Sku, order_lang: str) -> tuple[str, str, str]:
    """按报价语言冻结行展示三件套:(name, spec_text, unit)。

    spec_text 组自 **SPU.spec_jsonb ∪ SKU.spec_jsonb**(产品级 + 变体轴,PR9 规格分层后
    完整规格是两层并集);unit 解析 units.label_i18n 冻结成展示文字(零 join/无 FK)。
    """
    spu = (await db.execute(select(Spu).where(Spu.id == sku.spu_id))).scalar_one()
    by_key = await tmpl.suggestions_by_key(db, spu.category_code)
    merged = list(spu.spec_jsonb or []) + list(sku.spec_jsonb or [])
    name = display(sku.name_i18n, order_lang)
    spec_text = compose_spec_text(merged, by_key, order_lang)
    unit_row = (await db.execute(
        select(Unit).where(Unit.code == sku.unit))).scalar_one_or_none()
    unit = display(unit_row.label_i18n, order_lang) if unit_row is not None else sku.unit
    return name, spec_text, unit


async def assert_sku_available(db: AsyncSession, sku_id: int) -> Sku:
    """报价选料门禁(写时):SKU+SPU 均 ACTIVE 未删,否则 QuotationInvalidLineError。

    available=true 只是搜索期便利,写入口必须服务端硬挡,别让脏数据进报价。
    """
    sku = (await db.execute(
        select(Sku).where(Sku.id == sku_id, Sku.deleted_at.is_(None)))).scalar_one_or_none()
    if sku is None:
        raise QuotationInvalidLineError(f"SKU 不存在或已删: {sku_id}")
    spu = (await db.execute(select(Spu).where(Spu.id == sku.spu_id))).scalar_one_or_none()
    if spu is None or not sku_service.sku_available(sku, spu):
        raise QuotationInvalidLineError(f"SKU 不可报价(SKU/SPU 非 ACTIVE): {sku_id}")
    return sku


async def _next_quote_no(db: AsyncSession) -> str:
    # 单据号:Q{YYYYMM}{期内序号};按年月号段(编号服务)
    period = datetime.now(timezone.utc).strftime("%Y%m")
    seq = await allocate(db, NumberScope.QUOTATION, period)
    return format_code(NumberScope.QUOTATION, seq, period)


async def create_draft(db: AsyncSession, *, customer_id, currency, valid_until=None,
                       remark=None, salesperson_id=None, actor_user_id, actor_user_email,
                       request: Request | None = None) -> QuotationOrder:
    customer = await customer_service.get_customer(db, customer_id)
    language = customer.quote_language or DEFAULT_QUOTE_LANGUAGE
    # 报价人默认=建单人,草稿内可重指派(设计:salesperson_id 业务字段,created_by 审计归属)。
    order = QuotationOrder(no=await _next_quote_no(db), customer_id=customer_id,
                           salesperson_id=salesperson_id or actor_user_id,
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
    # 注:可选货门禁落在新的整单保存路径(save_order),旧 add_line 将于 API 重写时删除。
    lang = order.language
    # 快照默认由 SKU + SPU∪SKU 规格按报价语言组合,均可被入参覆盖(线下定稿优先)
    name_default, spec_default, unit_default = await compose_line_snapshot(db, sku, lang)
    name = name_snapshot if name_snapshot is not None else name_default
    spec_text = spec_text_snapshot if spec_text_snapshot is not None else spec_default
    unit = unit_snapshot if unit_snapshot is not None else unit_default
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


def _override(given, default):
    return given if given is not None else default


async def _reconcile_lines(db: AsyncSession, order: QuotationOrder, lines: list[dict]) -> Decimal:
    """按行 id 对账到期望态:有 id→UPDATE、库中缺席→DELETE、无 id→INSERT。返回总额。"""
    existing = {ln.id: ln for ln in await list_lines(db, order.id)}
    payload_ids = {ln["id"] for ln in lines if ln.get("id") is not None}
    # payload 出现库中不存在的行 id = 并发删除/篡改(乐观锁已过仍出现)→ 冲突。
    for lid in payload_ids:
        if lid not in existing:
            raise QuotationEditConflictError(f"报价行不存在: {lid}")
    for lid, row in existing.items():
        if lid not in payload_ids:
            await db.delete(row)

    total = Decimal("0")
    for idx, ln in enumerate(lines):
        sku = await assert_sku_available(db, ln["sku_id"])          # 写时挡非可选货
        name_d, spec_d, unit_d = await compose_line_snapshot(db, sku, order.language)
        name = _override(ln.get("name_snapshot"), name_d)
        spec_text = _override(ln.get("spec_text_snapshot"), spec_d)
        unit = _override(ln.get("unit_snapshot"), unit_d)
        line_total = Decimal(str(ln["unit_price"])) * Decimal(str(ln["qty"]))
        total += line_total
        sort_order = ln.get("sort_order", idx)
        if ln.get("id") is not None:
            row = existing[ln["id"]]
            row.sku_id = ln["sku_id"]
            row.name_snapshot, row.spec_text_snapshot, row.unit_snapshot = name, spec_text, unit
            row.unit_price, row.qty, row.line_total = ln["unit_price"], ln["qty"], line_total
            row.language, row.sort_order, row.remark = order.language, sort_order, ln.get("remark")
        else:
            db.add(QuotationLine(
                quotation_order_id=order.id, sku_id=ln["sku_id"], name_snapshot=name,
                spec_text_snapshot=spec_text, unit_snapshot=unit, unit_price=ln["unit_price"],
                qty=ln["qty"], line_total=line_total, language=order.language,
                sort_order=sort_order, remark=ln.get("remark")))
    await db.flush()
    return total


async def save_order(db: AsyncSession, *, order_id: int | None, customer_id, currency,
                     salesperson_id=None, valid_until=None, summary=None, language=None,
                     remark=None, lines: list[dict], expected_updated_at=None,
                     actor_user_id, actor_user_email, request: Request | None = None
                     ) -> QuotationOrder:
    """整单保存(新建或改草稿)。order_id=None 新建;否则 PUT 整单(仅 DRAFT + 乐观锁)。

    行按 id 对账(见 _reconcile_lines);total_amount=Σ行;快照按 SPU∪SKU 规格冻结。
    """
    if order_id is None:
        customer = await customer_service.get_customer(db, customer_id)
        order = QuotationOrder(
            no=await _next_quote_no(db), customer_id=customer_id,
            salesperson_id=salesperson_id or actor_user_id,
            language=language or customer.quote_language or DEFAULT_QUOTE_LANGUAGE,
            currency=currency, valid_until=valid_until, summary=summary, remark=remark,
            status=QuotationStatus.DRAFT, created_by=actor_user_id, total_amount=0)
        db.add(order)
        await db.flush()
        audit_action = AuditAction.CREATE
    else:
        order = await get_order(db, order_id)
        if order.status not in QUOTATION_EDITABLE:
            raise QuotationNotDraftError()
        if expected_updated_at is not None and order.updated_at != expected_updated_at:
            raise QuotationEditConflictError()
        order.customer_id = customer_id
        order.currency = currency
        if salesperson_id is not None:
            order.salesperson_id = salesperson_id
        order.valid_until, order.summary, order.remark = valid_until, summary, remark
        if language is not None:
            order.language = language
        audit_action = AuditAction.UPDATE

    order.total_amount = await _reconcile_lines(db, order, lines)
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.QUOTATION, action=audit_action,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=order.id, request=request, commit=False)
    await db.commit()
    await db.refresh(order)
    return order
