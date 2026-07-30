"""库存派生口径(单一源头,契约 §2)。

`compute_stock_balance` 是全仓「在库/可发」**唯一算法源头**:库存页、SO 详情库存块、
(出库步)锁内校验、(将来物化)回填,全部消费它,不许旁生第二份算法。

**本质**:货从采购起即归属某销售单(`purchase_order_lines.source_sales_order_line_id`
是 Ownership 非 Reference,守卫链保证无自由库存),故每个销售单每个 SKU 的
「订购/已入库/已出库/可发」四量可由既有 FK 单据链纯派生,不建任何库存表。

**防 join 放大(评审 P1)**:同一 SO 行可拆多张 PO、同一 PO 行可拆多张入库单,直接
`so_lines→po_lines→inbound_lines` 连表后 `SUM(so_lines.qty)` 会按分支数翻倍订购量。
必须三臂各自预聚合、再按 (sales_order_id, sku_id) FULL JOIN 合并。

**outbound 臂(出库步接入)**:`outbound_qty = SUM(qty) FROM outbound_order_lines JOIN
outbound_orders WHERE status='ISSUED' GROUP BY (sales_order_id, sku_id)`,`available =
inbound − outbound`。草稿出库不扣(仅 ISSUED 计),撤销出库回 DRAFT 自然恢复可发。
出库确认锁内校验与 unreceive 穿仓守卫经 `available_by_sku()` 复用同一 `_balance_subquery`。
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import compose_spec_text, display
from app.core.languages import INTERNAL_UI_LANGUAGE
from app.db.models.inbound_order import InboundOrder, InboundOrderLine, InboundOrderStatus
from app.db.models.outbound_order import (
    OutboundOrder,
    OutboundOrderLine,
    OutboundOrderStatus,
)
from app.db.models.purchase_order import PurchaseOrderLine
from app.db.models.sales_order import SalesOrder, SalesOrderLine, SalesOrderStatus
from app.db.models.sku import Sku
from app.db.models.spu import Spu
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


def _inbound_cte(sales_order_id, sku_id):
    """臂2:只从 RECEIVED 入库链按 (so, sku) 预聚合已入库量(归属经 PO行→SO行)。
    在途/作废入库不计(status=RECEIVED,口径同 D4)。

    不滤 SO 状态(与臂1 的 CONFIRMED 过滤不对称):守卫链保证 RECEIVED 入库的 SO 必为
    CONFIRMED —— 活动入库挡 PO 取消(has_active_inbound)、活动 PO 挡 SO 取消,故本臂
    看不到非 CONFIRMED 的 SO。若将来松动取消守卫(如允许带货取消),这里会静默出现
    ordered=0 的幽灵行,须同批补状态过滤。"""
    stmt = (
        select(
            SalesOrderLine.sales_order_id.label("so_id"),
            InboundOrderLine.sku_id.label("sku_id"),
            func.sum(InboundOrderLine.qty).label("inbound_qty"),
        )
        .join(InboundOrder, and_(
            InboundOrder.id == InboundOrderLine.inbound_order_id,
            InboundOrder.status == InboundOrderStatus.RECEIVED))
        .join(PurchaseOrderLine,
              PurchaseOrderLine.id == InboundOrderLine.purchase_order_line_id)
        .join(SalesOrderLine,
              SalesOrderLine.id == PurchaseOrderLine.source_sales_order_line_id)
        .group_by(SalesOrderLine.sales_order_id, InboundOrderLine.sku_id)
    )
    if sales_order_id is not None:
        stmt = stmt.where(SalesOrderLine.sales_order_id == sales_order_id)
    if sku_id is not None:
        stmt = stmt.where(InboundOrderLine.sku_id == sku_id)
    return stmt.subquery("inbound")


def _outbound_cte(sales_order_id, sku_id):
    """臂3:只从 ISSUED 出库单按 (so, sku) 预聚合已出库量(so_id 取自出库单头)。
    草稿/取消出库不计(status=ISSUED,契约 §1.5)—— 确认出库是唯一扣库存事件,
    撤销出库回 DRAFT 后本臂自然剔除,可发恢复。"""
    stmt = (
        select(
            OutboundOrder.sales_order_id.label("so_id"),
            OutboundOrderLine.sku_id.label("sku_id"),
            func.sum(OutboundOrderLine.qty).label("outbound_qty"),
        )
        .join(OutboundOrder, and_(
            OutboundOrder.id == OutboundOrderLine.outbound_order_id,
            OutboundOrder.status == OutboundOrderStatus.ISSUED))
        .group_by(OutboundOrder.sales_order_id, OutboundOrderLine.sku_id)
    )
    if sales_order_id is not None:
        stmt = stmt.where(OutboundOrder.sales_order_id == sales_order_id)
    if sku_id is not None:
        stmt = stmt.where(OutboundOrderLine.sku_id == sku_id)
    return stmt.subquery("outbound")


def _balance_subquery(sales_order_id, sku_id):
    """三臂各自预聚合,按键 (so_id, sku_id) FULL JOIN 合并 → 每 (so,sku) 一行四量
    (防 join 放大:直连会按下游分支数翻倍订购量,故必须先各臂聚合再合并)。
    available = inbound − outbound(全仓唯一可发口径)。"""
    o = _ordered_cte(sales_order_id, sku_id)
    i = _inbound_cte(sales_order_id, sku_id)
    b = _outbound_cte(sales_order_id, sku_id)
    oi = o.join(
        i, and_(o.c.so_id == i.c.so_id, o.c.sku_id == i.c.sku_id), full=True)
    # 第三臂 FULL JOIN:键取臂1/臂2 的 coalesce(某 (so,sku) 可能只在 inbound 出现)。
    joined = oi.join(
        b, and_(func.coalesce(o.c.so_id, i.c.so_id) == b.c.so_id,
                func.coalesce(o.c.sku_id, i.c.sku_id) == b.c.sku_id), full=True)
    so_id = func.coalesce(o.c.so_id, i.c.so_id, b.c.so_id).label("so_id")
    sku_id_col = func.coalesce(o.c.sku_id, i.c.sku_id, b.c.sku_id).label("sku_id")
    ordered_q = func.coalesce(o.c.ordered_qty, 0).label("ordered_qty")
    inbound_q = func.coalesce(i.c.inbound_qty, 0).label("inbound_qty")
    outbound_q = func.coalesce(b.c.outbound_qty, 0).label("outbound_qty")
    return (
        select(so_id, sku_id_col, ordered_q, inbound_q, outbound_q,
               (inbound_q - outbound_q).label("available_qty"))
        .select_from(joined)
        .subquery("balance")
    )


async def available_by_sku(db: AsyncSession, sales_order_id: int,
                           sku_ids: list[int] | None = None) -> dict[int, Decimal]:
    """锁内可发校验专用:复用 `_balance_subquery`(同一聚合口径,单一源头),
    只取 {sku_id → available},不做展示合成(compose_spec_text / SKU-SPU-Unit join)——
    出库确认锁内、unreceive 穿仓守卫在悲观锁下调用,轻量优先。

    调用方须先 `SELECT sales_orders FOR UPDATE` 锁 SO 头(串行化),再调本函数派生校验:
    锁保证读到的 available 不被并发出库/撤销抢改。缺席 sku → 该 (so,sku) 无任何单据流,
    available=0(dict.get 兜底)。"""
    bal = _balance_subquery(sales_order_id, None)
    stmt = select(bal.c.sku_id, bal.c.available_qty)
    if sku_ids:
        stmt = stmt.where(bal.c.sku_id.in_(sku_ids))
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
    """本函数是全仓库存「在库/可发」唯一口径(B 方案:纯派生,无库存表)。

    架构不变量:每个 RECEIVED 库存单位始终唯一归属一个 SO,系统无自由库存
    (purchase_order_lines.source_sales_order_line_id 是 Ownership 非 Reference)。
    库存页、SO 详情库存块、(出库步)锁内校验、(将来物化)回填全部消费本函数,
    不许旁生第二份算法。

    若下列条件之一出现,需升级承载层,详见
    docs/契约/2026-07-17-0321-库存增量-设计契约.md §6.2:
      - 实测变慢 → 物化 stock_balance 缓存(回填 = 本函数同一 SQL,set-based)
      - 动库存单据类型 >2(退货/盘亏/调拨)→ 流水台账
      - 需批次/溯源(哪批收货装哪柜)→ 出入库分配配对表
      - 退货可转配他单(自由库存出现)→ 补 仓×SKU 物理库存账
    任何让货脱离 SO 归属的新能力 = 业务模型变更,先过评审,勿静默扩派生臂。

    返回 (rows, total)。四量 + 展示三件套(SKU 当前档):
    - 过滤:sales_order_id / sku_id(聚合内下推)、q(SO单号/SKU编码/品名,聚合外匹配)。
    - scope 见 StockScope。page/size 均给时分页(聚合子查询外层),否则返回全量(SO 详情块)。
    """
    bal = _balance_subquery(sales_order_id, sku_id)
    # 展示投影:join 当前档 SKU/SPU/单位 + SO 号(合并键为 (so,sku),join 单值)。
    stmt = (
        select(
            bal.c.so_id, bal.c.sku_id,
            bal.c.ordered_qty, bal.c.inbound_qty, bal.c.outbound_qty, bal.c.available_qty,
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
