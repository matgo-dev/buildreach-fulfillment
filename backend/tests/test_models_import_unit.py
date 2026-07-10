def test_base_tables_registered():
    """基座表随 metadata 注册(sanity)。

    注:M0 时代这里曾断言"绝无业务表";M1 起本系统单库单 Base,业务表
    (categories / category_spec_attributes / ... )本就与基座表共享 Base.metadata,
    该排除断言前提已被 M1 设计推翻,故移除,仅保留基座表存在性 sanity。
    """
    from app.db.base import Base
    from app.db import models  # noqa: F401 触发注册
    tables = set(Base.metadata.tables.keys())
    assert {"users", "roles", "audit_logs"} <= tables
