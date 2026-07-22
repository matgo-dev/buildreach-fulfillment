import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.rbac.permissions_config import ROLE_PERMISSIONS
from app.rbac.constants import Permissions


@pytest.mark.asyncio
async def test_sync_seeds_admin_and_catalog_operator_roles_and_base_perms():
    import os
    dsn = os.environ.get("TEST_DATABASE_URL",
        "postgresql+psycopg://liujingjing@localhost:5433/fulfillment_test")
    engine = create_async_engine(dsn)
    from app.db.base import Base
    from app.db import models  # noqa: F401
    from app.rbac.sync import sync_rbac
    from app.seed import run_all_seeds
    from app.db.models.role import Role
    from app.db.models.permission import Permission
    from sqlalchemy import select
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.drop_all)
            await c.run_sync(Base.metadata.create_all)
        async with Session() as db:
            await sync_rbac(db)
            roles = {r.code for r in (await db.execute(select(Role))).scalars()}
            perms = {p.code for p in (await db.execute(select(Permission))).scalars()}
        assert roles == {"ADMIN", "PRODUCT_OPERATOR", "SALES", "PURCHASER", "LOGISTICS",
                         "FINANCE"}
        assert "auth:login" in perms
        assert "user:manage" in perms
        # 未实现域不应有权限泄漏(rfq 询价尚未做);product:* 已是商品域实权限,不在此列。
        assert not any(p.startswith(("rfq:",)) for p in perms)
        assert not any(p in perms for p in ("spu:manage", "sku:manage"))
        assert {"customer:manage", "customer:read", "product:read", "product:manage",
                "quote:manage"} <= perms
        # 采购增量(主流程第3步)权限点已同步。
        assert {"supplier:manage", "supplier:read", "purchase:manage", "purchase:read",
                "purchase:read_cost"} <= perms
        # 出库增量(主流程第6步)权限点已同步。
        assert {"outbound:read", "outbound:manage", "shipment:read", "shipment:manage",
                "receivable:read"} <= perms
        # 财务增量(主流程第11步)权限点已同步。
        assert {"receipt:read", "receipt:manage", "payment:read", "payment:manage"} <= perms
    finally:
        # 本测试对共享 fulfillment_test 做了 drop_all/create_all,会冲掉 session 级 fixture
        # 种下的引导管理员(sync_rbac 只建角色/权限,不建 admin 用户)。恢复基线:重跑
        # run_all_seeds 重种引导管理员,避免污染后续用 superadmin_headers 的测试(隔离修复)。
        async with Session() as db:
            await run_all_seeds(db)
        await engine.dispose()


def test_catalog_operator_has_read_and_manage():
    perms = ROLE_PERMISSIONS["PRODUCT_OPERATOR"]
    assert Permissions.PRODUCT_READ in perms
    assert Permissions.PRODUCT_MANAGE in perms


def test_admin_is_system_domain_only():
    # Q25「ADMIN 严格不触业务数据」:业务权限点(customer:* 兜底、product:read 过渡桥)已全部摘除,
    # ADMIN 只剩 auth base + 系统域(user/role/permission/system)。需兼管业务者给账号叠加功能角色。
    perms = ROLE_PERMISSIONS["ADMIN"]
    assert Permissions.PRODUCT_READ not in perms
    assert Permissions.PRODUCT_MANAGE not in perms
    assert Permissions.CUSTOMER_READ not in perms
    assert Permissions.CUSTOMER_MANAGE not in perms
    # 系统域权限仍在
    assert Permissions.USER_MANAGE in perms
    assert Permissions.ROLE_MANAGE in perms
    assert Permissions.SYSTEM_AUDIT in perms


def test_admin_no_longer_holds_quote_manage():
    # Q25「ADMIN 严格不触业务数据」:引入 SALES 后 quote:manage 归位到 SALES。
    assert Permissions.QUOTE_MANAGE not in ROLE_PERMISSIONS["ADMIN"]


def test_sales_role_permissions():
    perms = ROLE_PERMISSIONS["SALES"]
    assert Permissions.QUOTE_MANAGE in perms
    assert Permissions.CUSTOMER_READ in perms
    assert Permissions.PRODUCT_READ in perms
    # 销售持客户主数据全管(建客户→报价选客户同人同流);仍不碰商品主数据写、不碰系统域
    assert Permissions.CUSTOMER_MANAGE in perms
    assert Permissions.PRODUCT_MANAGE not in perms
    assert Permissions.USER_MANAGE not in perms
    # 销售不碰采购域(职责分离,采购整域是红线)
    assert Permissions.PURCHASE_READ not in perms
    assert Permissions.SUPPLIER_READ not in perms


def test_purchaser_role_permissions():
    perms = ROLE_PERMISSIONS["PURCHASER"]
    # 供应商主数据 + 采购单全生命周期 + 采购成本可见
    assert {Permissions.SUPPLIER_MANAGE, Permissions.SUPPLIER_READ, Permissions.PURCHASE_MANAGE,
            Permissions.PURCHASE_READ, Permissions.PURCHASE_READ_COST} <= set(perms)
    # 发起采购需读 SO(SO 售价非红线)+ 选料溯源
    assert Permissions.SALES_READ in perms
    assert Permissions.PRODUCT_READ in perms
    # 采购员不碰报价/客户写、不碰系统域
    assert Permissions.QUOTE_MANAGE not in perms
    assert Permissions.CUSTOMER_MANAGE not in perms
    assert Permissions.USER_MANAGE not in perms


def test_finance_role_permissions():
    perms = ROLE_PERMISSIONS["FINANCE"]
    # 收付款登记/核销 + 读账层(核销需读应收应付)。
    assert {Permissions.RECEIPT_READ, Permissions.RECEIPT_MANAGE, Permissions.PAYMENT_READ,
            Permissions.PAYMENT_MANAGE, Permissions.RECEIVABLE_READ,
            Permissions.PAYABLE_READ} <= set(perms)
    # 财务不碰录单域写(报价/销售/采购/出库)、不碰主数据写、不碰系统域(职责分离)。
    assert Permissions.QUOTE_MANAGE not in perms
    assert Permissions.SALES_MANAGE not in perms
    assert Permissions.PURCHASE_MANAGE not in perms
    assert Permissions.OUTBOUND_MANAGE not in perms
    assert Permissions.CUSTOMER_MANAGE not in perms
    assert Permissions.USER_MANAGE not in perms


def test_admin_no_finance_permissions():
    # ADMIN 纯系统域:收付款/核销权限一律不授(既有格局不动)。
    perms = ROLE_PERMISSIONS["ADMIN"]
    assert Permissions.RECEIPT_MANAGE not in perms
    assert Permissions.PAYMENT_MANAGE not in perms


def test_logistics_role_permissions():
    perms = ROLE_PERMISSIONS["LOGISTICS"]
    # 出库/发运全管 + 读 SO/库存/商品(建/派单)。
    assert {Permissions.OUTBOUND_READ, Permissions.OUTBOUND_MANAGE, Permissions.SHIPMENT_READ,
            Permissions.SHIPMENT_MANAGE, Permissions.SALES_READ, Permissions.INVENTORY_READ,
            Permissions.PRODUCT_READ} <= set(perms)
    # 应收=客户售价整表门控,物流不持;出库/柜零成本/售价,无红线开关。
    assert Permissions.RECEIVABLE_READ not in perms
    assert Permissions.PURCHASE_READ_COST not in perms
    assert Permissions.PURCHASE_READ not in perms
    # 不碰采购写/报价/客户写/系统域。
    assert Permissions.PURCHASE_MANAGE not in perms
    assert Permissions.QUOTE_MANAGE not in perms
    assert Permissions.CUSTOMER_MANAGE not in perms
    assert Permissions.USER_MANAGE not in perms
