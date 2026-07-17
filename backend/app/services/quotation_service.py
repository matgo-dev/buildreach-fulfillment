"""报价草稿服务:建草稿(language 默认由客户偏好映射)+ 逐行录入带快照。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import NumberScope, format_code
from app.core.exceptions import (
    QuotationLineReferencedBySalesOrderError,
    NotFoundError,
    QuotationCannotUnlockConvertedError,
    QuotationCannotVoidError,
    QuotationEditConflictError,
    QuotationEmptyLinesError,
    QuotationInvalidLineError,
    QuotationInvalidSalespersonError,
    QuotationInvalidTransitionError,
    QuotationNotDraftError,
)
from app.core.i18n import compose_spec_text, display
from app.core.languages import DEFAULT_QUOTE_LANGUAGE
from app.db.models.quotation import (
    QUOTATION_DELETABLE,
    QUOTATION_EDITABLE,
    QUOTATION_TRANSITIONS,
    QUOTATION_VOIDABLE,
    QuotationLine,
    QuotationOrder,
    QuotationStatus,
)
from app.db.models.customer import Customer
from app.db.models.sku import Sku
from app.db.models.spu import Spu
from app.db.models.unit import Unit
from app.db.models.user import User
from app.services import customer_service, sku_service, spec_template_service as tmpl, user_service
from app.services.numbering import allocate


def _compose_snapshot(sku: Sku, spu: Spu, by_key: dict, unit_row: Unit | None,
                      order_lang: str) -> tuple[str, str, str]:
    """纯内存组装行快照三件套(name, spec_text, unit)——所需 DB 取数由调用方预取传入。
    单行 compose_line_snapshot 与批量 _reconcile_lines 共用此组装逻辑(单一源头,防两处漂移)。

    spec_text 组自 **SPU.spec_jsonb ∪ SKU.spec_jsonb**(产品级 + 变体轴);unit 解析
    units.label_i18n 冻结成展示文字。
    """
    name = display(sku.name_i18n, order_lang)
    merged = list(spu.spec_jsonb or []) + list(sku.spec_jsonb or [])
    spec_text = compose_spec_text(merged, by_key, order_lang)
    unit = display(unit_row.label_i18n, order_lang) if unit_row is not None else sku.unit
    return name, spec_text, unit


async def compose_line_snapshot(db: AsyncSession, sku: Sku, order_lang: str) -> tuple[str, str, str]:
    """按报价语言冻结单个 SKU 的行展示三件套:(name, spec_text, unit)。逐行取数版本
    (批量写路径见 _reconcile_lines 的预取)。"""
    spu = (await db.execute(select(Spu).where(Spu.id == sku.spu_id))).scalar_one()
    by_key = await tmpl.suggestions_by_key(db, spu.category_code)
    unit_row = (await db.execute(
        select(Unit).where(Unit.code == sku.unit))).scalar_one_or_none()
    return _compose_snapshot(sku, spu, by_key, unit_row, order_lang)


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


async def get_order(db: AsyncSession, order_id: int) -> QuotationOrder:
    order = (await db.execute(
        select(QuotationOrder).where(QuotationOrder.id == order_id))).scalar_one_or_none()
    if order is None:
        raise NotFoundError(f"报价单不存在: {order_id}")
    return order


async def get_order_for_update(db: AsyncSession, order_id: int) -> QuotationOrder:
    """行级悲观锁读单(SELECT ... FOR UPDATE)。所有"读→改→写"的写路径(整单保存、状态跃迁、
    硬删)都经它取单:锁持到本事务提交,并发写被串行化,堵住无锁 RMW 的丢更新。
    乐观锁 expected_updated_at 是另一层职责——只探测"客户端视图过期"(GET 后别人改过),
    防丢更新靠这把行锁。纯读路径(GET 详情)不锁。"""
    order = (await db.execute(
        select(QuotationOrder).where(QuotationOrder.id == order_id)
        .with_for_update())).scalar_one_or_none()
    if order is None:
        raise NotFoundError(f"报价单不存在: {order_id}")
    return order


async def list_lines(db: AsyncSession, order_id: int) -> list[QuotationLine]:
    return list((await db.execute(
        select(QuotationLine).where(QuotationLine.quotation_order_id == order_id)
        .order_by(QuotationLine.sort_order))).scalars().all())


async def resolve_order_parties(db: AsyncSession, order: QuotationOrder) -> dict:
    """详情展示投影:客户 / 报价人展示名,按 id **直查 name**——不走 /users/selectable 口径。
    历史报价人即便后来停用 / 改角色(不再"可选")仍要显示姓名,不退化成 #id;查无才兜底 #id。
    与列表投影同源(列表用 join、详情用此),前端不再靠"可选人列表"反查。"""
    cust = (await db.execute(
        select(Customer.name).where(Customer.id == order.customer_id))).scalar_one_or_none()
    sp = (await db.execute(
        select(User.name).where(User.id == order.salesperson_id))).scalar_one_or_none()
    return {
        "customer_display": cust or f"#{order.customer_id}",
        "salesperson_display": sp or f"#{order.salesperson_id}",
    }


async def _assert_lines_deletable(db: AsyncSession, line_ids: list[int]) -> None:
    """删行引用保护(评审 S1):被(任意状态,含 CANCELLED)SO 行引用的报价行不可删——
    单据流 FK RESTRICT 的干净前置,防裸 IntegrityError 500。改 qty/价是 UPDATE 不触 FK,不经此。"""
    if not line_ids:
        return
    from app.db.models.sales_order import SalesOrderLine
    hit = (await db.execute(
        select(SalesOrderLine.source_quotation_line_id)
        .where(SalesOrderLine.source_quotation_line_id.in_(line_ids)).limit(1))).first()
    if hit:
        raise QuotationLineReferencedBySalesOrderError(
            f"报价行 {hit[0]} 已被销售单引用,不可删除")


async def _reconcile_lines(db: AsyncSession, order: QuotationOrder, lines: list[dict]) -> Decimal:
    """按行 id 对账到期望态:有 id→UPDATE、库中缺席→DELETE、无 id→INSERT。返回总额。"""
    existing = {ln.id: ln for ln in await list_lines(db, order.id)}
    payload_ids = {ln["id"] for ln in lines if ln.get("id") is not None}
    # payload 出现库中不存在的行 id = 并发删除/篡改(乐观锁已过仍出现)→ 冲突。
    for lid in payload_ids:
        if lid not in existing:
            raise QuotationEditConflictError(f"报价行不存在: {lid}")
    to_delete = [lid for lid in existing if lid not in payload_ids]
    await _assert_lines_deletable(db, to_delete)
    for lid in to_delete:
        await db.delete(existing[lid])

    # 批量预取(替代逐行 N+1:原每行 sku+spu+模板+单位 ~5 查):sku→spu→按品类去重的模板
    # by_key→单位,循环内纯内存组装。总查询数 ≈ 3 + 去重品类数,与行数无关。
    sku_ids = {ln["sku_id"] for ln in lines}
    skus = {s.id: s for s in (await db.execute(
        select(Sku).where(Sku.id.in_(sku_ids), Sku.deleted_at.is_(None)))).scalars()} if sku_ids else {}
    spu_ids = {s.spu_id for s in skus.values()}
    spus = {s.id: s for s in (await db.execute(
        select(Spu).where(Spu.id.in_(spu_ids)))).scalars()} if spu_ids else {}
    # 写时硬挡非可选货(SKU/SPU 均 ACTIVE 未删)——内存校验,口径同 assert_sku_available。
    for sid in sku_ids:
        sku = skus.get(sid)
        spu = spus.get(sku.spu_id) if sku else None
        if sku is None or spu is None or not sku_service.sku_available(sku, spu):
            raise QuotationInvalidLineError(f"SKU 不可报价(不存在/已删/非 ACTIVE): {sid}")
    by_key_by_cat = {c: await tmpl.suggestions_by_key(db, c)
                     for c in {spus[s.spu_id].category_code for s in skus.values()}}
    unit_codes = {s.unit for s in skus.values()}
    units = {u.code: u for u in (await db.execute(
        select(Unit).where(Unit.code.in_(unit_codes)))).scalars()} if unit_codes else {}

    total = Decimal("0")
    for idx, ln in enumerate(lines):
        row = existing[ln["id"]] if ln.get("id") is not None else None
        sku = skus[ln["sku_id"]]
        spu = spus[sku.spu_id]
        # 快照 freeze-at-pick:仅新增行或换了 SKU 才按当前主数据冻结(SPU∪SKU 规格 + 单位,
        # 按报价语言);同一 SKU 改数量/价/备注保留原定格值,主数据后续变更不回写已定行
        # (对齐 Odoo/SAP/NetSuite:行的单价/数量相对定格上下文才成立)。不采信客户端传入值。
        if row is not None and row.sku_id == ln["sku_id"]:
            name, spec_text, unit = row.name_snapshot, row.spec_text_snapshot, row.unit_snapshot
        else:
            name, spec_text, unit = _compose_snapshot(
                sku, spu, by_key_by_cat[spu.category_code], units.get(sku.unit), order.language)
        line_total = Decimal(str(ln["unit_price"])) * Decimal(str(ln["qty"]))
        total += line_total
        sort_order = ln.get("sort_order", idx)
        if row is not None:
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
    # 报价人写入口守卫:显式指派必须是"可选报价人"(ACTIVE + quote:manage),同下拉口径;
    # 缺省 = 建单销售本人(已过 quote:manage 门禁),无需再验。
    if salesperson_id is not None and not await user_service.is_selectable_salesperson(db, salesperson_id):
        raise QuotationInvalidSalespersonError()

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
        order = await get_order_for_update(db, order_id)
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


def _assert_transition(current: str, target: str) -> None:
    """合法转移守卫,读 model 层矩阵单一源头(QUOTATION_TRANSITIONS)。"""
    if target not in QUOTATION_TRANSITIONS[current]:
        raise QuotationInvalidTransitionError(f"非法转移: {current} → {target}")


async def _transition(db: AsyncSession, order_id: int, target: str, audit_action: AuditAction,
                      *, actor_user_id, actor_user_email, request: Request | None,
                      extra: dict | None = None) -> QuotationOrder:
    order = await get_order_for_update(db, order_id)
    _assert_transition(order.status, target)
    order.status = target
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.QUOTATION, action=audit_action,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=order.id, request=request, extra=extra, commit=False)
    await db.commit()
    await db.refresh(order)
    return order


async def lock_order(db: AsyncSession, *, order_id, actor_user_id, actor_user_email,
                     request: Request | None = None) -> QuotationOrder:
    """锁档 DRAFT→LOCKED(冻结基准),前置至少一行。

    显式仅 DRAFT:矩阵含 CONVERTED→LOCKED(SO 取消回退专用),不能只靠矩阵放行——
    否则公开端点可把已转报价拉回锁档,绕过 SO 取消守卫/留痕/双审计(评审 B1)。"""
    order = await get_order_for_update(db, order_id)
    if order.status != QuotationStatus.DRAFT:
        raise QuotationNotDraftError("Only a draft quotation can be locked via this endpoint")
    _assert_transition(order.status, QuotationStatus.LOCKED)
    if not await list_lines(db, order_id):
        raise QuotationEmptyLinesError()
    return await _transition(db, order_id, QuotationStatus.LOCKED, AuditAction.LOCK,
                             actor_user_id=actor_user_id, actor_user_email=actor_user_email,
                             request=request)


async def unlock_order(db: AsyncSession, *, order_id, actor_user_id, actor_user_email,
                       request: Request | None = None) -> QuotationOrder:
    """解锁 LOCKED→DRAFT;已转销售不可解(专有错误码)。"""
    order = await get_order_for_update(db, order_id)
    if order.status == QuotationStatus.CONVERTED:
        raise QuotationCannotUnlockConvertedError()
    return await _transition(db, order_id, QuotationStatus.DRAFT, AuditAction.UNLOCK,
                             actor_user_id=actor_user_id, actor_user_email=actor_user_email,
                             request=request)


async def void_order(db: AsyncSession, *, order_id, reason=None, actor_user_id, actor_user_email,
                     request: Request | None = None) -> QuotationOrder:
    """作废 DRAFT/LOCKED→VOID(曾有效现废弃;reason 落 audit)。

    显式前置守卫(对齐 lock/unlock 的精确报错约定):非可作废态(CONVERTED 终态、VOID 已作废)
    → 专有 QuotationCannotVoidError,不退化成通用「非法转移」。可作废集派生自矩阵(QUOTATION_VOIDABLE)。
    """
    order = await get_order_for_update(db, order_id)
    if order.status not in QUOTATION_VOIDABLE:
        raise QuotationCannotVoidError()
    return await _transition(db, order_id, QuotationStatus.VOID, AuditAction.VOID,
                             actor_user_id=actor_user_id, actor_user_email=actor_user_email,
                             request=request, extra={"reason": reason} if reason else None)


async def list_orders(db: AsyncSession, *, status=None, customer_id=None, salesperson_id=None,
                      keyword=None, created_from=None, created_to=None, sort="created_at",
                      page: int = 1, size: int = 20) -> tuple[list[dict], int]:
    """报价列表:筛选(状态/客户/报价人/关键词/日期)+ 排序(created_at|total_amount 降序)
    + 分页。返回(投影行, 总数)。投影 display 客户/报价人名 + 行数,列表不返 lines。"""
    conds = []
    if status:
        conds.append(QuotationOrder.status == status)
    if customer_id:
        conds.append(QuotationOrder.customer_id == customer_id)
    if salesperson_id:
        conds.append(QuotationOrder.salesperson_id == salesperson_id)
    if created_from:
        conds.append(QuotationOrder.created_at >= created_from)
    if created_to:
        # created_to 是 date;若用 <= 会被当成当天 00:00:00,漏掉当天白天创建的报价。
        # 改为 < 次日零点,含 created_to 当天全天(半开区间 [created_from, created_to+1))。
        conds.append(QuotationOrder.created_at < created_to + timedelta(days=1))
    if keyword:
        like = f"%{keyword}%"
        conds.append(or_(QuotationOrder.no.ilike(like),
                         Customer.name.ilike(like)))

    total = (await db.execute(
        select(func.count(QuotationOrder.id))
        .join(Customer, Customer.id == QuotationOrder.customer_id)
        .where(*conds))).scalar_one()

    line_count = (select(func.count(QuotationLine.id))
                  .where(QuotationLine.quotation_order_id == QuotationOrder.id)
                  .scalar_subquery())
    order_col = (QuotationOrder.total_amount.desc() if sort == "total_amount"
                 else QuotationOrder.created_at.desc())
    rows = (await db.execute(
        select(QuotationOrder, Customer.name, User.name, line_count.label("lc"))
        .join(Customer, Customer.id == QuotationOrder.customer_id)
        .join(User, User.id == QuotationOrder.salesperson_id)
        .where(*conds).order_by(order_col)
        .offset((page - 1) * size).limit(size))).all()

    items = [{
        "id": o.id, "no": o.no, "summary": o.summary,
        "customer_display": cust_name,
        "salesperson_display": sp_name,
        "status": o.status, "currency": o.currency, "total_amount": o.total_amount,
        "valid_until": o.valid_until, "line_count": lc, "created_at": o.created_at,
    } for (o, cust_name, sp_name, lc) in rows]
    return items, total


async def delete_order(db: AsyncSession, *, order_id, actor_user_id, actor_user_email,
                       request: Request | None = None) -> None:
    """硬删报价单(仅草稿;行 CASCADE)。草稿=从没弄好可删,非草稿走作废。
    引用保护:曾转过销售单(含已取消)的报价行仍被 SO 行 FK 引用,不可硬删 → 41411。"""
    order = await get_order_for_update(db, order_id)
    if order.status not in QUOTATION_DELETABLE:
        raise QuotationNotDraftError()
    await _assert_lines_deletable(db, [ln.id for ln in await list_lines(db, order_id)])
    await write_audit(db, resource_type=AuditResourceType.QUOTATION, action=AuditAction.DELETE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=order.id, request=request, commit=False)
    await db.delete(order)
    await db.commit()
