"""0036 头表 total_amount 舍入回填验证 —— 隔离临时库,绝不碰 fulfillment_dev/test 数据。

自建独立临时库,create_all 建 schema → 种「表头 total_amount 漂移(≠Σ行 line_total)」的报价/
采购/销售各一张 → 经 Operations.context 驱动真 upgrade() → 断言三头表都被修回 Σ 行额 → 再跑
_run 验幂等(不再改动)。同步 psycopg 直连(不复用 conftest 的 async 测试引擎)。
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
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

_MIG_DB = "fulfillment_mig_check_0036"
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
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0036_fix_header_amount_rounding.py"
    spec = importlib.util.spec_from_file_location("mig_0036", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed_fixture(s: Session) -> None:
    """三头表各一张:两行 line_total=1.10 → 真值 Σ=2.20;头 total_amount 故意种成漂移值 2.21。"""
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
    # 报价:头漂移 2.21,两行各 1.10 → 应修回 2.20
    s.add(QuotationOrder(id=1, no="Q1", customer_id=1, salesperson_id=1, language="en",
                         currency="USD", status="DRAFT", total_amount="2.21", created_by=1))
    s.flush()
    for i, sku_id in enumerate((1, 2)):
        s.add(QuotationLine(id=i + 1, quotation_order_id=1, sku_id=sku_id, name_snapshot="x",
                            spec_text_snapshot="", unit_snapshot="ton", unit_price="0.99",
                            qty="1.115", line_total="1.10", language="en", sort_order=i))
    # 销售:头漂移 2.21,两行各 1.10 → 应修回 2.20
    s.add(SalesOrder(id=1, no="SO1", source_quotation_id=1, customer_id=1, salesperson_id=1,
                     language="en", currency="USD", status="CONFIRMED", total_amount="2.21",
                     created_by=1))
    s.flush()
    for i, (sku_id, qlid) in enumerate(((1, 1), (2, 2))):
        s.add(SalesOrderLine(id=i + 1, sales_order_id=1, sku_id=sku_id,
                             source_quotation_line_id=qlid, name_snapshot="x", unit_price="0.99",
                             qty="1.115", line_total="1.10", language="en"))
    # 采购:头漂移 2.21,两行各 1.10 → 应修回 2.20
    s.add(Supplier(id=1, code="S001", name="供应商", status="ACTIVE"))
    s.flush()
    s.add(PurchaseOrder(id=1, no="PO1", source_sales_order_id=1, supplier_id=1, currency="USD",
                        status="DRAFT", total_amount="2.21", created_by=1))
    s.flush()
    for i, solid in enumerate((1, 2)):
        s.add(PurchaseOrderLine(id=i + 1, purchase_order_id=1, sku_id=i + 1,
                                source_sales_order_line_id=solid, name_snapshot="x",
                                unit_price="0.99", qty="1.115", line_total="1.10", language="en"))
    s.commit()


def _totals(engine) -> dict[str, float]:
    with engine.connect() as conn:
        return {
            "q": float(conn.execute(text("SELECT total_amount FROM quotation_orders WHERE id=1")).scalar_one()),
            "so": float(conn.execute(text("SELECT total_amount FROM sales_orders WHERE id=1")).scalar_one()),
            "po": float(conn.execute(text("SELECT total_amount FROM purchase_orders WHERE id=1")).scalar_one()),
        }


@pytest.mark.filterwarnings("ignore")
def test_migration_0036_backfills_drifted_headers_idempotent():
    _create_db(_MIG_DB)
    engine = create_engine(f"{_BASE}/{_MIG_DB}")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as s:
            _seed_fixture(s)
        assert _totals(engine) == {"q": 2.21, "so": 2.21, "po": 2.21}, "种子应为漂移值 2.21"

        mig = _load_migration()
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                mig.upgrade()
        assert _totals(engine) == {"q": 2.20, "so": 2.20, "po": 2.20}, "三头表应修回 Σ行额 2.20"

        # 幂等:再跑一次 _run,不再改动(IS DISTINCT FROM 已一致行不写)。
        with engine.begin() as conn:
            mig._run(conn)
        assert _totals(engine) == {"q": 2.20, "so": 2.20, "po": 2.20}, "幂等:重跑不应改动已修正的值"
    finally:
        engine.dispose()
        _drop_db(_MIG_DB)
