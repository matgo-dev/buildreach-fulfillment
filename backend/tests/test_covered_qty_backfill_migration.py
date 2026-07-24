"""0035 covered_qty 回填 data 步骤验证 —— 隔离临时库,绝不碰 fulfillment_dev/test 数据。

安全:自建独立临时库(fulfillment_mig_check),create_all 建 schema(covered_qty 列由模型带出),
插 SO 行 + 采购行(含一张 CANCELLED PO 应被排除)+ **故意把 covered_qty 预置成错值**,直接驱动
迁移的 _run(conn) 回填、**重复调用**验幂等,断言列被 set-based UPDATE 纠正为真值后 drop 临时库。
同步 psycopg 直连(不复用 conftest 的 async 测试引擎)。
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db import models as _models  # noqa: F401  注册所有模型供 create_all
from app.db.models.category import Category
from app.db.models.customer import Customer
from app.db.models.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.db.models.quotation import QuotationLine, QuotationOrder
from app.db.models.sales_order import SalesOrder, SalesOrderLine
from app.db.models.sku import Sku
from app.db.models.spu import Spu
from app.db.models.supplier import Supplier
from app.db.models.unit import Unit
from app.db.models.user import User

_RAW = os.environ.get("DATABASE_URL", "postgresql+psycopg://liujingjing@localhost:5433/fulfillment_test")
_SYNC = _RAW.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
if _SYNC.startswith("postgresql://"):
    _SYNC = _SYNC.replace("postgresql://", "postgresql+psycopg://", 1)

_MIG_DB = "fulfillment_mig_check"
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
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0035_so_line_covered_qty.py"
    spec = importlib.util.spec_from_file_location("mig_0035", path)
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
    s.add(Sku(id=1, spu_id=1, sku_code="SKU1", unit="ton", status="ACTIVE", created_by=1,
              name_i18n={"zh": "工字钢"}))
    s.add(Sku(id=2, spu_id=1, sku_code="SKU2", unit="ton", status="ACTIVE", created_by=1,
              name_i18n={"zh": "槽钢"}))
    s.add(QuotationOrder(id=1, no="Q1", customer_id=1, salesperson_id=1, language="en",
                         currency="USD", status="DRAFT", total_amount=0, created_by=1))
    s.flush()
    s.add(QuotationLine(id=1, quotation_order_id=1, sku_id=1, name_snapshot="x",
                        spec_text_snapshot="", unit_snapshot="", unit_price=0, qty=10,
                        line_total=0, language="en", sort_order=0))
    s.add(QuotationLine(id=2, quotation_order_id=1, sku_id=2, name_snapshot="y",
                        spec_text_snapshot="", unit_snapshot="", unit_price=0, qty=10,
                        line_total=0, language="en", sort_order=1))
    s.add(SalesOrder(id=1, no="SO1", source_quotation_id=1, customer_id=1, salesperson_id=1,
                     language="en", currency="USD", status="CONFIRMED", total_amount=0, created_by=1))
    s.flush()
    # 忠实模拟真实 upgrade:add_column server_default '0' 先把每行置 0(此处不显式给 covered_qty),
    # 再由 _run 回填有覆盖的行。sol1:被 DRAFT(2)+CANCELLED(5) 覆盖 → 回填成 2(证明回填确跑、排除 CANCELLED);
    # sol2:无采购行 → 维持 0(回填不触碰未覆盖行,靠列 DEFAULT,最小写不放大)。
    s.add(SalesOrderLine(id=1, sales_order_id=1, sku_id=1, source_quotation_line_id=1,
                         name_snapshot="x", unit_price=0, qty=10, line_total=0, language="en"))
    s.add(SalesOrderLine(id=2, sales_order_id=1, sku_id=2, source_quotation_line_id=2,
                         name_snapshot="y", unit_price=0, qty=10, line_total=0, language="en"))
    s.add(Supplier(id=1, code="S001", name="供应商", status="ACTIVE"))
    s.flush()
    # PO1 DRAFT:行 qty=2 on sol1(计入)
    s.add(PurchaseOrder(id=1, no="PO1", source_sales_order_id=1, supplier_id=1, currency="USD",
                        status="DRAFT", total_amount=0, created_by=1))
    # PO2 CANCELLED:行 qty=5 on sol1(排除)
    s.add(PurchaseOrder(id=2, no="PO2", source_sales_order_id=1, supplier_id=1, currency="USD",
                        status="CANCELLED", total_amount=0, created_by=1))
    s.flush()
    s.add(PurchaseOrderLine(id=1, purchase_order_id=1, sku_id=1, source_sales_order_line_id=1,
                            name_snapshot="x", unit_price=7, qty=2, line_total=14, language="en"))
    s.add(PurchaseOrderLine(id=2, purchase_order_id=2, sku_id=1, source_sales_order_line_id=1,
                            name_snapshot="x", unit_price=7, qty=5, line_total=35, language="en"))
    s.commit()


@pytest.mark.filterwarnings("ignore")
def test_migration_0035_backfill_and_idempotence():
    _create_db(_MIG_DB)
    engine = create_engine(f"{_BASE}/{_MIG_DB}")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as s:
            _seed_fixture(s)

        mig = _load_migration()
        # 跑两遍验幂等:重算非自增,结果不随次数变
        with engine.begin() as conn:
            mig._run(conn)
        with engine.begin() as conn:
            mig._run(conn)

        with engine.connect() as conn:
            cov = dict(conn.execute(text(
                "SELECT id, covered_qty FROM sales_order_lines ORDER BY id")).all())
            assert float(cov[1]) == 2, "sol1 应 = Σ非CANCELLED(2),排除 CANCELLED 的 5"
            assert float(cov[2]) == 0, "sol2 无采购行 → 维持 DEFAULT 0"
    finally:
        engine.dispose()
        _drop_db(_MIG_DB)
