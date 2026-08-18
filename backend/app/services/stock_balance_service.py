"""库存余额口径(单一源头,契约 §2)。

`compute_stock_balance` 是全仓「在库/可发」**唯一算法源头**:库存页、SO 详情库存块、
(出库步)锁内校验全部消费它,不许旁生第二份算法。

**本质**:货从采购起即归属某销售单(`purchase_order_lines.source_sales_order_line_id`
是 Ownership 非 Reference,守卫链保证无自由库存),故库存余额按 (sales_order_id, sku_id)
落库。`inventory_movements` 是库存事实流水,`inventory_balances` 是库存页/出库校验读模型。

**防 join 放大(评审 P1)**:同一 SO 行可拆多张 PO、同一 PO 行可拆多张入库单,直接
`so_lines→po_lines→inbound_lines` 连表后 `SUM(so_lines.qty)` 会按分支数翻倍订购量。
订购量仍单独预聚合,再与库存余额按 (sales_order_id, sku_id) FULL JOIN 合并。

**库存事件**:确认入库追加入库流水并增加余额;撤销入库追加冲回流水并减少余额;
确认出库追加出库流水并减少可发。草稿出库不扣,ISSUED 为正向履约终点并持续计入已出库。
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import compose_spec_text, display
from app.core.languages import INTERNAL_UI_LANGUAGE
from app.db.models.sales_order import SalesOrder, SalesOrderLine, SalesOrderStatus
from app.db.models.sku import Sku
from app.db.models.spu import Spu
from app.db.models.stock import InventoryBalance
from app.db.models.unit import Unit
from app.services import spec_template_service as tmpl


class StockScope:
    """行包含口径(同一函数一个 scope,不许两套 SQL)。
    - AVAILABLE(默认,/inventory 在库视角):available_qty > 0,已履约完的行退出。
    - HISTORY(履约史):inbound>0 OR outbound>0,允许慢。
    - ALL(SO 详情块):该过滤域全部 (so,sku) 行,含已入 0,对照订购。
    """
    AVAILABLE = "available"
    HISTORY = "history"
    ALL = "all"
    PAGE_SCOPES = (AVAILABLE, HISTORY)  # /inventory 端点可选值(ALL 仅内部 SO 详情块用)


def _ordered_cte(sales_order_id, sku_id):
    """臂1:只从 CONFIRMED SO 行按 (so, sku) 预聚合订购量,不碰下游。"""
    stmt = (
        select(
            SalesOrderLine.sales_order_id.label("so_id"),
            SalesOrderLine.sku_id.label("sku_id"),
            func.sum(SalesOrderLine.qty).label("ordered_qty"),
        )
        .join(SalesOrder, SalesOrder.id == SalesOrderLine.sales_order_id)
        .where(SalesOrder.status == SalesOrderStatus.CONFIRMED)
        .group_by(SalesOrderLine.sales_order_id, SalesOrderLine.sku_id)
    )
    if sales_order_id is not None:
        stmt = stmt.where(SalesOrderLine.sales_order_id == sales_order_id)
    if sku_id is not None:
        stmt = stmt.where(SalesOrderLine.sku_id == sku_id)
    return stmt.subquery("ordered")


def _stock_cte(sales_order_id, sku_id):
    """臂2:从库存余额表按 (so, sku) 取已入库/已出库/可发。

    在途入库不写余额,草稿出库不写余额。库存写入只在状态机确认事件内发生。"""
    stmt = (
        select(
            InventoryBalance.sales_order_id.label("so_id"),
            InventoryBalance.sku_id.label("sku_id"),
            InventoryBalance.inbound_qty.label("inbound_qty"),
            InventoryBalance.outbound_qty.label("outbound_qty"),
            InventoryBalance.disposition_qty.label("disposition_qty"),
            InventoryBalance.available_qty.label("available_qty"),
        )
        .select_from(InventoryBalance)
    )
    if sales_order_id is not None:
        stmt = stmt.where(InventoryBalance.sales_order_id == sales_order_id)
    if sku_id is not None:
        stmt = stmt.where(InventoryBalance.sku_id == sku_id)
    return stmt.subquery("stock")


def _balance_subquery(sales_order_id, sku_id):
    """订购预聚合 + 库存余额 FULL JOIN → 每 (so,sku) 一行四量。

    ordered 来源仍是 SO 行,库存三量来自 inventory_balances。available = inbound − outbound
    由 DB 生成列维护。
    """
    o = _ordered_cte(sales_order_id, sku_id)
    s = _stock_cte(sales_order_id, sku_id)
    joined = o.join(
        s, and_(o.c.so_id == s.c.so_id, o.c.sku_id == s.c.sku_id), full=True)
    so_id = func.coalesce(o.c.so_id, s.c.so_id).label("so_id")
    sku_id_col = func.coalesce(o.c.sku_id, s.c.sku_id).label("sku_id")
    ordered_q = func.coalesce(o.c.ordered_qty, 0).label("ordered_qty")
    inbound_q = func.coalesce(s.c.inbound_qty, 0).label("inbound_qty")
    outbound_q = func.coalesce(s.c.outbound_qty, 0).label("outbound_qty")
    disposition_q = func.coalesce(s.c.disposition_qty, 0).label("disposition_qty")
    available_q = func.coalesce(s.c.available_qty, 0).label("available_qty")
    return (
        select(so_id, sku_id_col, ordered_q, inbound_q, outbound_q,
               disposition_q, available_q)
        .select_from(joined)
        .subquery("balance")
    )


async def available_by_sku(db: AsyncSession, sales_order_id: int,
                           sku_ids: list[int] | None = None) -> dict[int, Decimal]:
    """锁内可发校验专用:读取 `inventory_balances`(同一余额口径,单一源头),
    只取 {sku_id → available},不做展示合成(compose_spec_text / SKU-SPU-Unit join)——
    出库确认锁内、unreceive 穿仓守卫在悲观锁下调用,轻量优先。

    调用方须先 `SELECT sales_orders FOR UPDATE` 锁 SO 头(串行化),再调本函数余额校验:
    锁保证读到的 available 不被并发出库/撤销抢改。缺席 sku → 该 (so,sku) 无任何单据流,
    available=0(dict.get 兜底)。"""
    stmt = select(InventoryBalance.sku_id, InventoryBalance.available_qty).where(
        InventoryBalance.sales_order_id == sales_order_id)
    if sku_ids:
        stmt = stmt.where(InventoryBalance.sku_id.in_(sku_ids))
    rows = (await db.execute(stmt)).all()
    return {sku_id: Decimal(str(av)) for sku_id, av in rows}


def _scope_filter(bal, scope: str):
    """行包含谓词。ALL → 无过滤(SO 详情块含全部行)。"""
    if scope == StockScope.AVAILABLE:
        return [bal.c.available_qty > 0]
    if scope == StockScope.HISTORY:
        return [or_(bal.c.inbound_qty > 0, bal.c.outbound_qty > 0)]
    return []  # ALL


async def _compose_display(db: AsyncSession, rows) -> list[dict]:
    """合并行展示字段取 **SKU 当前档**(品名/规格串/单位),非行快照(合并行无单一快照来源)。
    语言取该行所属 SO 的 language(单 SO 内语言恒定)。规格串复用 compose_spec_text 单一口径。"""
    # 规格串按 SKU 变体轴模板翻译:按 category_code 批量取模板,页内去重(≤ size 行,类目更少)。
    cat_codes = {r.category_code for r in rows}
    by_cat: dict[str, dict] = {}
    for code in cat_codes:
        by_cat[code] = await tmpl.suggestions_by_key(db, code)
    out = []
    for r in rows:
        # 内部读投影按界面语言渲染,**不取** SalesOrder.language ——
        # 那是发给客户的单据语言,用它渲染内部列表会中英混排(见 core/languages.py)。
        lang = INTERNAL_UI_LANGUAGE
        out.append({
            "sales_order_id": r.so_id,
            "sales_order_no": r.so_no,
            "sku_id": r.sku_id,
            "sku_code": r.sku_code,
            "name": display(r.name_i18n, lang),
            "spec_text": compose_spec_text(
                list(r.spec_jsonb or []), by_cat[r.category_code], lang),
            "unit": display(r.unit_label, lang) if r.unit_label else r.unit_code,
            "ordered_qty": float(r.ordered_qty),
            "inbound_qty": float(r.inbound_qty),
            "outbound_qty": float(r.outbound_qty),
            "disposition_qty": float(r.disposition_qty),
            "available_qty": float(r.available_qty),
        })
    return out


async def compute_stock_balance(
    db: AsyncSession, *,
    sales_order_id: int | None = None,
    sku_id: int | None = None,
    q: str | None = None,
    scope: str = StockScope.AVAILABLE,
    page: int | None = None,
    size: int | None = None,
) -> tuple[list[dict], int]:
    """本函数是全仓库存「在库/可发」唯一读口径。

    架构不变量:每个 RECEIVED 库存单位始终唯一归属一个 SO,系统无自由库存
    (purchase_order_lines.source_sales_order_line_id 是 Ownership 非 Reference)。
    库存页、SO 详情库存块、(出库步)锁内校验全部消费本函数,不许旁生第二份算法。
    任何让货脱离 SO 归属的新能力 = 业务模型变更,先过评审,勿静默扩库存余额。

    返回 (rows, total)。四量 + 展示三件套(SKU 当前档):
    - 过滤:sales_order_id / sku_id(聚合内下推)、q(SO单号/SKU编码/品名,聚合外匹配)。
    - scope 见 StockScope。page/size 均给时分页(聚合子查询外层),否则返回全量(SO 详情块)。
    """
    bal = _balance_subquery(sales_order_id, sku_id)
    # 展示投影:join 当前档 SKU/SPU/单位 + SO 号(合并键为 (so,sku),join 单值)。
    stmt = (
        select(
            bal.c.so_id, bal.c.sku_id,
            bal.c.ordered_qty, bal.c.inbound_qty, bal.c.outbound_qty,
            bal.c.disposition_qty, bal.c.available_qty,
            SalesOrder.no.label("so_no"),
            Sku.sku_code, Sku.name_i18n, Sku.spec_jsonb,
            Sku.unit.label("unit_code"), Unit.label_i18n.label("unit_label"),
            Spu.category_code,
        )
        .join(SalesOrder, SalesOrder.id == bal.c.so_id)
        .join(Sku, Sku.id == bal.c.sku_id)
        .join(Spu, Spu.id == Sku.spu_id)
        .join(Unit, Unit.code == Sku.unit, isouter=True)
    )
    conds = _scope_filter(bal, scope)
    if q:
        like = f"%{q}%"
        conds.append(or_(SalesOrder.no.ilike(like), Sku.sku_code.ilike(like),
                         Sku.search_text.ilike(like)))
    if conds:
        stmt = stmt.where(*conds)
    stmt = stmt.order_by(bal.c.so_id, bal.c.sku_id)

    if page is not None and size is not None:
        # count(*) OVER () 让总数随当页行一趟返回,避免默认 paginate 把三臂聚合 + FULL JOIN
        # (全库最贵查询)为算 total 再整条重跑一遍(2× → 1×)。窗口按过滤后、limit 前的全集计数。
        # 越界空页(page 超末页)窗口无行可取 → 回落单独 count 一次拿正确总数(仅此边角付 2×)。
        paged = (stmt.add_columns(func.count().over().label("total_count"))
                 .offset((page - 1) * size).limit(size))
        rows = list((await db.execute(paged)).all())
        if rows:
            total = int(rows[0].total_count)
        elif page <= 1:
            total = 0
        else:
            total = (await db.execute(
                select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one()
    else:
        rows = list((await db.execute(stmt)).all())
        total = len(rows)
    return await _compose_display(db, rows), total
