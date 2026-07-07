"""登录失败限流(进程内 dict,MVP 单机够用)。

规则:维度 = (email, ip),窗口 60s 内累计 ≥5 次失败 → 锁 5 分钟。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from app.core.config import settings


@dataclass
class _Bucket:
    failures: list[float] = field(default_factory=list)
    locked_until: float = 0.0


class LoginRateLimiter:
    def __init__(
        self,
        window_seconds: int | None = None,
        max_failures: int | None = None,
        lock_seconds: int | None = None,
    ):
        self.window = window_seconds or settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS
        self.max_failures = max_failures or settings.LOGIN_RATE_LIMIT_MAX_FAILURES
        self.lock_seconds = lock_seconds or settings.LOGIN_RATE_LIMIT_LOCK_SECONDS
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._lock = threading.Lock()

    def _key(self, email: str, ip: str) -> tuple[str, str]:
        return (email.strip().lower(), ip or "-")

    def is_locked(self, email: str, ip: str) -> bool:
        with self._lock:
            bucket = self._buckets.get(self._key(email, ip))
            if not bucket:
                return False
            return time.time() < bucket.locked_until

    def record_failure(self, email: str, ip: str) -> bool:
        """记一次失败。返回 True 表示**本次失败触发了锁定**。"""
        now = time.time()
        with self._lock:
            key = self._key(email, ip)
            bucket = self._buckets.setdefault(key, _Bucket())
            # 已锁,不再计数
            if now < bucket.locked_until:
                return False
            # 清理窗口外的失败
            bucket.failures = [t for t in bucket.failures if now - t < self.window]
            bucket.failures.append(now)
            if len(bucket.failures) >= self.max_failures:
                bucket.locked_until = now + self.lock_seconds
                bucket.failures.clear()
                return True
            return False

    def reset(self, email: str, ip: str) -> None:
        with self._lock:
            self._buckets.pop(self._key(email, ip), None)

    def clear_all(self) -> None:
        """测试用。"""
        with self._lock:
            self._buckets.clear()


login_rate_limiter = LoginRateLimiter()
