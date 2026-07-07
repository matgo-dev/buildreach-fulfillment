def test_metadata_only_base_tables():
    from app.db.base import Base
    from app.db import models  # noqa: F401 触发注册
    tables = set(Base.metadata.tables.keys())
    # 只应有基座表,绝无业务表
    assert "users" in tables
    assert "roles" in tables
    assert "audit_logs" in tables
    business = {"products", "rfqs", "quotes", "buyer_organizations",
                "supplier_organizations", "zones", "carts", "categories"}
    assert not (tables & business), f"业务表泄漏进基座 metadata: {tables & business}"
