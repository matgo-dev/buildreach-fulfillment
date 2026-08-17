"""0040 库存落库迁移验证 —— 隔离临时库,绝不碰 fulfillment_dev/test 数据。

create_all 建终态 schema 后删除库存派生表,还原迁移前形态;再经 Operations.context
驱动真 upgrade(),用旧实时聚合口径对比新 inventory_balances。覆盖:
- RECEIVED 入库计入,IN_TRANSIT 入库不计入;
- ISSUED 出库计入,DRAFT 出库不计入;
- 完全履约行 available=0 仍保留余额行。
"""
from __future__ import annotations

import importlib.util
import os
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db import models as _models  # noqa: F401  注册所有模型供 create_all
from app.db.base import Base
from app.db.models.category import Category
from app.db.models.customer import Customer
from app.db.models.inbound_order import InboundOrder, InboundOrderLine
from app.db.models.outbound_order import OutboundOrder, OutboundOrderLine
from app.db.models.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.db.models.quotation import QuotationLine, QuotationOrder
from app.db.models.sales_order import SalesOrder, SalesOrderLine
from app.db.models.shipment_order import ShipmentOrder
from app.db.models.sku import Sku
from app.db.models.spu import Spu
from app.db.models.supplier import Supplier
from app.db.models.unit import Unit
from app.db.models.user import User

_RAW = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://liujingjing@localhost:5433/fulfillment_test")
_SYNC = _RAW.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
if _SYNC.startswith("postgresql://"):
    _SYNC = _SYNC.replace("postgresql://", "postgresql+psycopg://", 1)

_MIG_DB = "fulfillment_mig_check_0040"
_BASE, _ = _SYNC.rsplit("/", 1)
_ADMIN_DSN = f"{_BASE}/postgres"


def _create_db(name: str) -> None:
    admin = create_engine(_ADMIN_DSN, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {name} (FORCE)"))
        c.execute(text(f"CREATE DATABASE {name}"))
    admin.dispose()


def _drop_db(name: str) -> None:
    admin = create_engine(_ADMIN_DSN, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {name} (FORCE)"))
    admin.dispose()


def _load_migration():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / (
        "0040_stock_persistence.py")
    spec = importlib.util.spec_from_file_location("mig_0040", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed_fixture(s: Session) -> None:
    s.add(User(id=1, name="op", password_hash="x"))
    s.add(Customer(id=1, code="C001", name="客户"))
    s.add(Unit(code="ton", label_i18n={"zh": "吨"}, sort_order=0))
    s.add(Category(code="10", parent_code=None, name_i18n={"zh": "钢材"}, level=1,
                   is_leaf=True, sort_order=0))
    s.flush()

    s.add(Spu(id=1, spu_code="SPU1", category_code="10", name_i18n={"zh": "钢"},
              spec_jsonb=[], status="ACTIVE", created_by=1))
    s.flush()
    s.add(Sku(id=1, spu_id=1, sku_code="SKU1", unit="ton", status="ACTIVE",
              created_by=1, name_i18n={"zh": "工字钢"}))
    s.add(Sku(id=2, spu_id=1, sku_code="SKU2", unit="ton", status="ACTIVE",
              created_by=1, name_i18n={"zh": "槽钢"}))
    s.add(QuotationOrder(id=1, no="Q1", customer_id=1, salesperson_id=1,
                         language="zh", currency="USD", status="CONVERTED",
                         total_amount=0, created_by=1))
    s.flush()
    s.add(QuotationLine(id=1, quotation_order_id=1, sku_id=1, name_snapshot="SKU1",
                        spec_text_snapshot="", unit_snapshot="吨", unit_price=0,
                        qty=10, line_total=0, language="zh", sort_order=0))
    s.add(QuotationLine(id=2, quotation_order_id=1, sku_id=2, name_snapshot="SKU2",
                        spec_text_snapshot="", unit_snapshot="吨", unit_price=0,
                        qty=5, line_total=0, language="zh", sort_order=1))
    s.add(SalesOrder(id=1, no="SO1", source_quotation_id=1, customer_id=1,
                     salesperson_id=1, language="zh", currency="USD", status="CONFIRMED",
                     total_amount=0, created_by=1))
    s.flush()
    s.add(SalesOrderLine(id=1, sales_order_id=1, sku_id=1, source_quotation_line_id=1,
                         name_snapshot="SKU1", spec_text_snapshot="", unit_snapshot="吨",
                         unit_price=0, qty=10, line_total=0, language="zh"))
    s.add(SalesOrderLine(id=2, sales_order_id=1, sku_id=2, source_quotation_line_id=2,
                         name_snapshot="SKU2", spec_text_snapshot="", unit_snapshot="吨",
                         unit_price=0, qty=5, line_total=0, language="zh"))
    s.add(Supplier(id=1, code="S001", name="供应商", status="ACTIVE"))
    s.flush()

    s.add(PurchaseOrder(id=1, no="PO1", source_sales_order_id=1, supplier_id=1,
                        currency="USD", status="CONFIRMED", total_amount=0, created_by=1))
    s.flush()
    s.add(PurchaseOrderLine(id=1, purchase_order_id=1, sku_id=1,
                            source_sales_order_line_id=1, name_snapshot="SKU1",
                            spec_text_snapshot="", unit_snapshot="吨", unit_price=0,
                            qty=10, line_total=0, language="zh", sort_order=0))
    s.add(PurchaseOrderLine(id=2, purchase_order_id=1, sku_id=2,
                            source_sales_order_line_id=2, name_snapshot="SKU2",
                            spec_text_snapshot="", unit_snapshot="吨", unit_price=0,
                            qty=5, line_total=0, language="zh", sort_order=1))
    s.flush()

    s.add(InboundOrder(id=1, no="IN1", purchase_order_id=1, status="RECEIVED",
                       created_by=1))
    s.add(InboundOrder(id=2, no="IN2", purchase_order_id=1, status="IN_TRANSIT",
                       created_by=1))
    s.flush()
    s.add(InboundOrderLine(id=1, inbound_order_id=1, purchase_order_line_id=1, sku_id=1,
                           name_snapshot="SKU1", spec_text_snapshot="", unit_snapshot="吨",
                           language="zh", qty=10, sort_order=0))
    s.add(InboundOrderLine(id=2, inbound_order_id=1, purchase_order_line_id=2, sku_id=2,
                           name_snapshot="SKU2", spec_text_snapshot="", unit_snapshot="吨",
                           language="zh", qty=5, sort_order=1))
    # 在途入库不应进入旧口径和迁移回填。
    s.add(InboundOrderLine(id=3, inbound_order_id=2, purchase_order_line_id=1, sku_id=1,
                           name_snapshot="SKU1", spec_text_snapshot="", unit_snapshot="吨",
                           language="zh", qty=3, sort_order=0))

    s.add(ShipmentOrder(id=1, no="SH1", status="OPEN", created_by=1))
    s.flush()
    s.add(OutboundOrder(id=1, no="OUT1", sales_order_id=1, shipment_id=1,
                        status="ISSUED", created_by=1))
    s.add(OutboundOrder(id=2, no="OUT2", sales_order_id=1, shipment_id=1,
                        status="DRAFT", created_by=1))
    s.flush()
    s.add(OutboundOrderLine(id=1, outbound_order_id=1, sales_order_line_id=1,
                            sku_id=1, qty=4))
    s.add(OutboundOrderLine(id=2, outbound_order_id=1, sales_order_line_id=2,
                            sku_id=2, qty=5))
    # 草稿出库不应进入旧口径和迁移回填。
    s.add(OutboundOrderLine(id=3, outbound_order_id=2, sales_order_line_id=1,
                            sku_id=1, qty=2))
    s.commit()


def _old_realtime_aggregation(engine) -> dict[tuple[int, int], tuple[Decimal, Decimal, Decimal]]:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            WITH inbound AS (
                SELECT
                    sol.sales_order_id,
                    iol.sku_id,
                    SUM(iol.qty)::numeric(18,3) AS inbound_qty
                FROM inbound_order_lines iol
                JOIN inbound_orders io ON io.id = iol.inbound_order_id
                JOIN purchase_order_lines pol ON pol.id = iol.purchase_order_line_id
                JOIN sales_order_lines sol ON sol.id = pol.source_sales_order_line_id
                WHERE io.status = 'RECEIVED'
                GROUP BY sol.sales_order_id, iol.sku_id
            ),
            outbound AS (
                SELECT
                    oo.sales_order_id,
                    ool.sku_id,
                    SUM(ool.qty)::numeric(18,3) AS outbound_qty
                FROM outbound_order_lines ool
                JOIN outbound_orders oo ON oo.id = ool.outbound_order_id
                WHERE oo.status = 'ISSUED'
                GROUP BY oo.sales_order_id, ool.sku_id
            ),
            keys AS (
                SELECT sales_order_id, sku_id FROM inbound
                UNION
                SELECT sales_order_id, sku_id FROM outbound
            )
            SELECT
                k.sales_order_id,
                k.sku_id,
                COALESCE(i.inbound_qty, 0)::numeric(18,3) AS inbound_qty,
                COALESCE(o.outbound_qty, 0)::numeric(18,3) AS outbound_qty,
                (COALESCE(i.inbound_qty, 0) - COALESCE(o.outbound_qty, 0))::numeric(18,3)
                    AS available_qty
            FROM keys k
            LEFT JOIN inbound i USING (sales_order_id, sku_id)
            LEFT JOIN outbound o USING (sales_order_id, sku_id)
            ORDER BY k.sales_order_id, k.sku_id
        """)).all()
    return {(r.sales_order_id, r.sku_id): (r.inbound_qty, r.outbound_qty, r.available_qty)
            for r in rows}


def _persisted_balances(engine) -> dict[tuple[int, int], tuple[Decimal, Decimal, Decimal]]:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT sales_order_id, sku_id, inbound_qty, outbound_qty, available_qty
            FROM inventory_balances
            ORDER BY sales_order_id, sku_id
        """)).all()
    return {(r.sales_order_id, r.sku_id): (r.inbound_qty, r.outbound_qty, r.available_qty)
            for r in rows}


def _movement_counts(engine) -> dict[str, int]:
    with engine.connect() as conn:
        return dict(conn.execute(text("""
            SELECT movement_type, COUNT(*)::int
            FROM inventory_movements
            GROUP BY movement_type
            ORDER BY movement_type
        """)).all())


@pytest.mark.filterwarnings("ignore")
def test_migration_0040_backfills_balances_from_old_realtime_stock():
    _create_db(_MIG_DB)
    engine = create_engine(f"{_BASE}/{_MIG_DB}")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as s:
            _seed_fixture(s)

        expected = _old_realtime_aggregation(engine)
        assert expected == {
            (1, 1): (Decimal("10.000"), Decimal("4.000"), Decimal("6.000")),
            (1, 2): (Decimal("5.000"), Decimal("5.000"), Decimal("0.000")),
        }

        # create_all 是模型终态,已带库存表;剥掉它们还原迁移前形态,让 upgrade 真跑。
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE inventory_movements"))
            conn.execute(text("DROP TABLE inventory_balances"))

        mig = _load_migration()
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                mig.upgrade()

        assert _persisted_balances(engine) == expected
        assert _movement_counts(engine) == {
            "INBOUND_RECEIVE": 2,
            "OUTBOUND_ISSUE": 2,
        }

        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                mig.downgrade()
        with engine.connect() as conn:
            tables = {r[0] for r in conn.execute(text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN ('inventory_movements', 'inventory_balances')
            """))}
        assert tables == set()
    finally:
        engine.dispose()
        _drop_db(_MIG_DB)
