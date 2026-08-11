"""生产配置 fail-fast 单测。"""
from types import SimpleNamespace

import pytest

from app.core.production_guard import validate_production_settings


def _valid_prod(**overrides):
    data = dict(
        DEPLOY_ENV="production",
        JWT_SECRET_KEY="prod-random-secret-key-1234567890",
        SUPER_ADMIN_INITIAL_PASSWORD="ProdInitPass123",
        DATABASE_URL="postgresql+asyncpg://fulfillment:prod-db-pass@db:5432/fulfillment",
        ENABLE_API_DOCS=False,
        REFRESH_COOKIE_SECURE=True,
        ENABLE_HSTS=True,
        REFRESH_COOKIE_SAMESITE="lax",
        CORS_ORIGINS=["https://erp.example.com"],
        STORAGE_BACKEND="s3",
        S3_ENDPOINT_URL="https://s3.example.com",
        S3_ACCESS_KEY="prod-access-key",
        S3_SECRET_KEY="prod-secret-key",
        S3_BUCKET="fulfillment-attachments",
    )
    data.update(overrides)
    return SimpleNamespace(**data)


def test_production_guard_allows_valid_production_config():
    validate_production_settings(_valid_prod())


def test_production_guard_ignores_staging_config():
    validate_production_settings(SimpleNamespace(
        DEPLOY_ENV="staging",
        JWT_SECRET_KEY="change-me",
        CORS_ORIGINS=["http://127.0.0.1"],
        STORAGE_BACKEND="s3",
        S3_ENDPOINT_URL="http://minio:9000",
    ))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("JWT_SECRET_KEY", "change-me-to-random-min-16-chars", "JWT_SECRET_KEY"),
        ("SUPER_ADMIN_INITIAL_PASSWORD", "ChangeMe12345", "SUPER_ADMIN_INITIAL_PASSWORD"),
        ("ENABLE_API_DOCS", True, "ENABLE_API_DOCS"),
        ("REFRESH_COOKIE_SECURE", False, "REFRESH_COOKIE_SECURE"),
        ("ENABLE_HSTS", False, "ENABLE_HSTS"),
        ("REFRESH_COOKIE_SAMESITE", "none", "REFRESH_COOKIE_SAMESITE"),
        ("STORAGE_BACKEND", "local", "STORAGE_BACKEND"),
        ("S3_ENDPOINT_URL", "http://minio:9000", "S3_ENDPOINT_URL"),
        ("S3_SECRET_KEY", "change-me-strong-minio", "S3_SECRET_KEY"),
    ],
)
def test_production_guard_rejects_known_unsafe_values(field, value, message):
    settings = _valid_prod(**{field: value})
    with pytest.raises(RuntimeError, match=message):
        validate_production_settings(settings)


@pytest.mark.parametrize("origins", [["*"], ["http://erp.example.com"], ["https://localhost:3000"]])
def test_production_guard_rejects_non_public_https_cors(origins):
    settings = _valid_prod(CORS_ORIGINS=origins)
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        validate_production_settings(settings)
