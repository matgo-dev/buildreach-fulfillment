"""全局配置:从 .env 读取,Pydantic 校验后注入。履约系统基座裁剪版。"""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8",
        case_sensitive=False, extra="ignore",
    )

    # 数据库 — 复用现有 brew PG @5433,独立 database
    DATABASE_URL: str = "postgresql+asyncpg://liujingjing@localhost:5433/fulfillment_dev"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600

    # JWT(签名算法钉死在 core/security.py 的 _JWT_ALG 常量,不做可配置项:只用 HS256 对称密钥,
    # env 可配只徒增误配面)
    JWT_SECRET_KEY: str = Field(..., min_length=16)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # 引导管理员(始终种入)。初始密码必填无默认值 —— 漏配起不来(同 JWT_SECRET_KEY)。
    SUPER_ADMIN_EMAIL: str = "superadmin@fulfillment.local"
    SUPER_ADMIN_INITIAL_PASSWORD: str = Field(...)

    # bcrypt 工作因子。生产默认 12(安全基线不变);测试环境降到 4 提速(见 conftest.py)。
    BCRYPT_ROUNDS: int = 12

    LOG_LEVEL: str = "INFO"

    # CORS
    CORS_ORIGINS_RAW: str = Field(default="http://localhost:3000", alias="CORS_ORIGINS")
    CORS_ALLOW_CREDENTIALS: bool = True

    # 登录限流(单机内存,第一道减速带)
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 60
    LOGIN_RATE_LIMIT_MAX_FAILURES: int = 5
    LOGIN_RATE_LIMIT_LOCK_SECONDS: int = 300

    # 账号级登录锁定(落用户行,第二道;换 IP/重启进程不绕过)
    ACCOUNT_LOCK_THRESHOLD: int = 10
    ACCOUNT_LOCK_MINUTES: int = 15

    # Refresh cookie
    REFRESH_COOKIE_NAME: str = "refresh_token"
    REFRESH_COOKIE_PATH: str = "/api/v1/auth"
    REFRESH_COOKIE_MAX_AGE: int = 7 * 24 * 3600
    REFRESH_COOKIE_SECURE: bool = False
    REFRESH_COOKIE_SAMESITE: str = "lax"

    # refresh 重放宽限窗:同族 refresh cookie 被并发轮换(多标签页休眠唤醒)时,父 token
    # 在首次 used_at 后此秒数内被复用视为竞态而非重放 —— 容忍、发新、不撤族;窗外复用
    # 判重放 → 撤整族。窗从首次 used_at 起算、不因窗内重放延后(防无限撑窗)。
    REFRESH_REPLAY_GRACE_SECONDS: int = 60

    # Trace / Proxy(前置可信网关时才置 true)
    TRUST_INBOUND_TRACE_ID: bool = False
    TRUST_PROXY: bool = False

    # API 文档(/docs /redoc /openapi.json)开关。默认关(安全默认值),本地开发在 .env 打开
    ENABLE_API_DOCS: bool = False

    # HSTS 响应头开关。HTTP 阶段浏览器忽略 HSTS,接 HTTPS 后打开(与 REFRESH_COOKIE_SECURE 同思路)
    ENABLE_HSTS: bool = False

    # 对象存储(附件)—— local | s3。s3 兼容 MinIO(本地)/ 生产 S3 兼容云对象存储
    STORAGE_BACKEND: str = "local"
    S3_ENDPOINT_URL: str = ""      # MinIO/OSS endpoint,如 http://localhost:9000
    S3_REGION: str = "cn-hangzhou"
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_BUCKET: str = "fulfillment-attachments"
    S3_PUBLIC_BASE_URL: str = ""   # 公开资产基址(留空则不支持 public_url)
    IMAGE_PATH_PREFIX: str = "/static"  # LocalDiskStorage.public_url() 前缀(本期未挂载,预留)

    # 单据附件(报关扫描件等,中转上传;非商品图)。
    ATTACHMENT_MAX_SIZE_BYTES: int = 50 * 1024 * 1024   # 单文件上限 50MB(后端最后防线)
    ATTACHMENT_ORPHAN_TTL_HOURS: int = 72               # 孤儿(未提交表单)可关联/下载时效
    ATTACHMENT_ORPHAN_QUOTA_COUNT: int = 20             # 单用户活动孤儿数量上限
    ATTACHMENT_ORPHAN_QUOTA_BYTES: int = 100 * 1024 * 1024  # 单用户活动孤儿字节上限 100MB
    ATTACHMENT_MAX_PER_OWNER: int = 10                  # 单报关记录关联附件数上限

    @computed_field  # type: ignore[misc]
    @property
    def CORS_ORIGINS(self) -> List[str]:
        return [s.strip() for s in self.CORS_ORIGINS_RAW.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
