"""0022 规格串迁移的 data 步骤验证 —— 隔离临时库,绝不碰 fulfillment_dev/test 数据。

安全:自建一个独立临时库(fulfillment_mig_check),create_all 建 schema、插模拟 dev 实况的
fixture(29 链分类 + 兜底 spec/range 模板 + 2 个电子秤 SKU + 一条 en 报价行),直接驱动迁移
的 _run(conn) 并**重复调用**验幂等,断言结果后 drop 掉临时库。不复用 conftest 的 async
测试引擎(那个跑在 fulfillment_test 上),故本文件是同步 psycopg 直连。
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
from app.db.models.quotation import QuotationLine, QuotationOrder
from app.db.models.sku import Sku
from app.db.models.spu import Spu
from app.db.models.unit import Unit
from app.db.models.user import User
from app.db.models.category_spec_attribute import CategorySpecAttribute

# conftest 已把 DATABASE_URL 置成 test DSN(psycopg 或 asyncpg 前缀);统一转 sync psycopg。
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
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0022_spec_descriptor.py"
    spec = importlib.util.spec_from_file_location("mig_0022", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed_fixture(s: Session) -> None:
    """ORM 建 fixture(应用层默认值自动补齐:时间戳/status/must_change_password 等)。"""
    s.add(User(id=1, name="op", password_hash="x"))
    s.add(Customer(id=1, code="C001", name="客户"))
    s.add(Unit(code="ea", label_i18n={"zh": "台"}, sort_order=0))
    s.add(Category(code="29", parent_code=None, name_i18n={"zh": "量刃具"}, level=1,
                   is_leaf=False, sort_order=0))
    s.add(Category(code="29.001", parent_code="29", name_i18n={"zh": "电子秤"}, level=2,
                   is_leaf=True, sort_order=0))
    s.flush()

    # 29 层兜底 spec(待删)+ range(测排序:浅层在前)
    for key, order in (("spec", 10), ("range", 20)):
        s.add(CategorySpecAttribute(category_code="29", key=key, label_i18n={"zh": key},
                                    value_type="string", options=None, unit="",
                                    sort_order=order, source="seed", scope="sku"))

    s.add(Spu(id=1, spu_code="SPU1", category_code="29.001", name_i18n={"zh": "电子秤"},
              spec_jsonb=[], status="ACTIVE", created_by=1))
    s.flush()
    # sku1:spec + range 轴;sku2:仅 spec
    s.add(Sku(id=1, spu_id=1, sku_code="SKU1", unit="ea", status="ACTIVE", created_by=1,
              name_i18n={"zh": "电子秤A"},
              spec_jsonb=[{"key": "spec", "value": "15kg/0.5g"},
                          {"key": "range", "value": "0.02–15kg"}]))
    s.add(Sku(id=2, spu_id=1, sku_code="SKU2", unit="ea", status="ACTIVE", created_by=1,
              name_i18n={"zh": "电子秤B"},
              spec_jsonb=[{"key": "spec", "value": "30kg/1g"}]))

    s.add(QuotationOrder(id=1, no="Q1", customer_id=1, salesperson_id=1, language="en",
                         currency="USD", status="DRAFT", total_amount=0, created_by=1))
    s.flush()
    s.add(QuotationLine(id=1, quotation_order_id=1, sku_id=1, name_snapshot="x",
                        spec_text_snapshot="STALE", unit_snapshot="", unit_price=0, qty=1,
                        line_total=0, language="en", sort_order=0))
    s.commit()


@pytest.mark.filterwarnings("ignore")
def test_migration_0022_data_steps_and_idempotence():
    _create_db(_MIG_DB)
    engine = create_engine(f"{_BASE}/{_MIG_DB}")
    try:
        Base.metadata.create_all(engine)  # before_create 事件会先建 pg_trgm 扩展
        with Session(engine) as s:
            _seed_fixture(s)

        mig = _load_migration()
        # 跑两遍:第二遍必须是幂等 no-op(spec 已 remap、模板已删)且结果不变
        with engine.begin() as conn:
            mig._run(conn)
        with engine.begin() as conn:
            mig._run(conn)

        with engine.connect() as conn:
            # ① division 模板落 29.001(unit g)
            div = conn.execute(text("SELECT unit, value_type, scope, source FROM category_spec_attributes "
                                    "WHERE category_code='29.001' AND key='division'")).one()
            assert (div.unit, div.value_type, div.scope, div.source) == ("g", "number", "sku", "seed")
            # ② 29 兜底 spec 删除;range 保留
            keys29 = {r[0] for r in conn.execute(text(
                "SELECT key FROM category_spec_attributes WHERE category_code='29'"))}
            assert keys29 == {"range"}
            # 且模板行不重复(幂等:division 只一行)
            assert conn.execute(text("SELECT count(*) FROM category_spec_attributes "
                                     "WHERE key='division'")).scalar() == 1

            # ③ SKU spec 重映射:spec→division,值剥单位为数值(int 保持 int)
            s1 = conn.execute(text("SELECT spec_jsonb FROM skus WHERE id=1")).scalar()
            s2 = conn.execute(text("SELECT spec_jsonb FROM skus WHERE id=2")).scalar()
            d1 = {i["key"]: i["value"] for i in s1}
            assert d1 == {"division": 0.5, "range": "0.02–15kg"}
            assert {i["key"]: i["value"] for i in s2} == {"division": 1}
            assert not any(i["key"] == "spec" for i in s1 + s2)

            # ④ 受影响 SKU 重算 search_text:钉住 build_sku_search_text 实际产出的关键 token
            # ——分度值 + range 值 + SKU 名 + SPU 名 + sku_code 全在(变体轴 ∪ SPU 上下文)。
            st1 = conn.execute(text("SELECT search_text FROM skus WHERE id=1")).scalar()
            assert "0.5" in st1 and "0.02–15kg" in st1  # 分度值 + range 轴值
            assert "电子秤A" in st1 and "电子秤" in st1  # SKU 名 + SPU 名
            assert "SKU1" in st1  # sku_code

            # ⑤ 行快照重算(en 行):只 SKU 轴、去标签、值+单位紧凑、` / ` 连接、按模板序
            snap = conn.execute(text("SELECT spec_text_snapshot FROM quotation_lines WHERE id=1")).scalar()
            assert snap == "0.02–15kg / 0.5g"
    finally:
        engine.dispose()
        _drop_db(_MIG_DB)


def _seed_negative_fixture(s: Session) -> None:
    """负例:一个非 29 子树品类(08 紧固件)误挂 key='spec' 兜底模板 + 一个值带 '/' 的 SKU
    (M8/1.25,螺纹规格,非分度值)。该品类祖先链拿不到 division 模板,③ 不会碰它 → remap 后
    仍残留 key='spec' → 残留守卫必 raise。另建 29 兜底模板一行,用来断言异常回滚后它仍在。"""
    s.add(User(id=1, name="op", password_hash="x"))
    # 29 树 + 29 兜底 spec 模板(仅用于断言 raise 回滚后 ② 的删除被撤销、模板仍在)
    s.add(Category(code="29", parent_code=None, name_i18n={"zh": "量刃具"}, level=1,
                   is_leaf=False, sort_order=0))
    s.add(Category(code="29.001", parent_code="29", name_i18n={"zh": "电子秤"}, level=2,
                   is_leaf=True, sort_order=0))
    s.add(CategorySpecAttribute(category_code="29", key="spec", label_i18n={"zh": "spec"},
                                value_type="string", options=None, unit="",
                                sort_order=10, source="seed", scope="sku"))
    # 08 紧固件树 + 兜底 spec 模板(无 division)
    s.add(Category(code="08", parent_code=None, name_i18n={"zh": "紧固件"}, level=1,
                   is_leaf=True, sort_order=0))
    s.add(CategorySpecAttribute(category_code="08", key="spec", label_i18n={"zh": "spec"},
                                value_type="string", options=None, unit="",
                                sort_order=10, source="seed", scope="sku"))
    s.add(Unit(code="ea", label_i18n={"zh": "件"}, sort_order=0))
    s.flush()

    s.add(Spu(id=1, spu_code="SPU8", category_code="08", name_i18n={"zh": "螺栓"},
              spec_jsonb=[], status="ACTIVE", created_by=1))
    s.flush()
    # 值含 '/' 但语义是螺纹规格,非 "Xkg/Yg" 分度值;品类无 division 模板 → 必残留
    s.add(Sku(id=1, spu_id=1, sku_code="SKU8", unit="ea", status="ACTIVE", created_by=1,
              name_i18n={"zh": "螺栓A"},
              spec_jsonb=[{"key": "spec", "value": "M8/1.25"}]))
    s.commit()


@pytest.mark.filterwarnings("ignore")
def test_migration_0022_non_scale_category_raises_and_rolls_back():
    """F1 最危险路径:非电子秤品类的 spec 值(含 '/')绝不被静默错映射成 division,而是残留
    守卫 raise、alembic 单事务整体回滚——库不脏(SKU 值原样、29 兜底模板仍在)。"""
    name = f"{_MIG_DB}_neg"
    _create_db(name)
    engine = create_engine(f"{_BASE}/{name}")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as s:
            _seed_negative_fixture(s)

        mig = _load_migration()
        with pytest.raises(RuntimeError) as ei:
            with engine.begin() as conn:
                mig._run(conn)
        msg = str(ei.value)
        assert "SKU8" in msg or "id=1" in msg  # 消息含该 sku 标识
        assert "spec" in msg

        # 整体回滚、库不脏:08 SKU 的 spec_jsonb 原样、29 兜底 spec 模板仍在(② 删除被撤销)
        with engine.connect() as conn:
            spec = conn.execute(text("SELECT spec_jsonb FROM skus WHERE id=1")).scalar()
            assert spec == [{"key": "spec", "value": "M8/1.25"}]
            keys29 = {r[0] for r in conn.execute(text(
                "SELECT key FROM category_spec_attributes WHERE category_code='29'"))}
            assert "spec" in keys29
    finally:
        engine.dispose()
        _drop_db(name)
