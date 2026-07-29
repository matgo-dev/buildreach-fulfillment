"""0037 schema 严谨迁移验证 —— 隔离临时库,绝不碰 fulfillment_dev/test 数据。

自建临时库,create_all(模型终态已含两个 status CHECK、已无 users 冗余索引)→ 还原迁移前
形态(删两 CHECK + 补回三条 ix_users_*)→ 真 upgrade() → 断言 CHECK 生效(UPDATE 非法 status
被拒)且冗余索引已删、唯一索引仍在 → downgrade() 断言可逆。同步 psycopg 直连。
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db import models as _models  # noqa: F401  注册所有模型供 create_all
from app.db.models.user import User

_RAW = os.environ.get("DATABASE_URL", "postgresql+psycopg://liujingjing@localhost:5433/fulfillment_test")
_SYNC = _RAW.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
if _SYNC.startswith("postgresql://"):
    _SYNC = _SYNC.replace("postgresql://", "postgresql+psycopg://", 1)

_MIG_DB = "fulfillment_mig_check_0037"
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
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0037_schema_rigor_checks_indexes.py"
    spec = importlib.util.spec_from_file_location("mig_0037", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _indexes(engine, table: str) -> set[str]:
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename = :t"), {"t": table})}


def _constraints(engine, table: str) -> set[str]:
    # table 为测试内受控字面量('users'/'audit_logs'),直接内联(bind 参数会与 ::regclass 转型冲突)。
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(text(
            f"SELECT conname FROM pg_constraint WHERE conrelid = '{table}'::regclass"))}


@pytest.mark.filterwarnings("ignore")
def test_migration_0037_checks_and_index_cleanup_reversible():
    _create_db(_MIG_DB)
    engine = create_engine(f"{_BASE}/{_MIG_DB}")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as s:
            s.add(User(id=1, name="op", password_hash="x", status="ACTIVE"))
            s.commit()
        # 还原迁移前形态:删模型终态的两 CHECK,补回三条冗余非唯一索引
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users DROP CONSTRAINT ck_users_status"))
            conn.execute(text("ALTER TABLE audit_logs DROP CONSTRAINT ck_audit_logs_status"))
            conn.execute(text("CREATE INDEX ix_users_email ON users(email)"))
            conn.execute(text("CREATE INDEX ix_users_username ON users(username)"))
            conn.execute(text("CREATE INDEX ix_users_phone ON users(phone)"))
            conn.execute(text("CREATE INDEX ix_spus_category_code ON spus(category_code)"))

        mig = _load_migration()
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                mig.upgrade()

        # CHECK 生效:非法 status 被拒(UPDATE 只碰 status 列,隔离出 CHECK 违约)
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text("UPDATE users SET status = 'BOGUS' WHERE id = 1"))
        assert {"ck_users_status"} <= _constraints(engine, "users")
        assert {"ck_audit_logs_status"} <= _constraints(engine, "audit_logs")

        # users 冗余非唯一索引已删,唯一索引仍在
        uidx = _indexes(engine, "users")
        assert not ({"ix_users_email", "ix_users_username", "ix_users_phone"} & uidx)
        assert {"uq_users_email", "uq_users_username", "uq_users_phone"} <= uidx
        # spus 默认 opclass 冗余索引已删,pattern_ops 前缀索引仍在
        sidx = _indexes(engine, "spus")
        assert "ix_spus_category_code" not in sidx
        assert "ix_spus_category_code_prefix" in sidx

        # downgrade 可逆:CHECK 移除、冗余索引回补
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                mig.downgrade()
        assert "ck_users_status" not in _constraints(engine, "users")
        assert "ck_audit_logs_status" not in _constraints(engine, "audit_logs")
        assert {"ix_users_email", "ix_users_username", "ix_users_phone"} <= _indexes(engine, "users")
        assert "ix_spus_category_code" in _indexes(engine, "spus")
    finally:
        engine.dispose()
        _drop_db(_MIG_DB)
