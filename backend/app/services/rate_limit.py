"""登录失败限流(进程内 dict,MVP 单机够用)。

规则:维度 = (email, ip),窗口 60s 内累计 ≥5 次失败 → 锁 5 分钟。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from app.core.config import settings

# 桶字典硬上限:防随机 identifier(不存在账号走廉价路径)无限堆积撑爆进程内存。
# 到顶时先扫掉已过期桶,仍满则逐出最接近过期的(见 _evict)。10k 桶内存开销可忽略。
_MAX_BUCKETS = 10_000


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

    def _active_until(self, b: _Bucket) -> float:
        """该桶还需保留到何时:锁定到期 与 最近一次失败的窗口末端,取大;过此即可安全丢弃。"""
        last_fail = b.failures[-1] if b.failures else 0.0
        return max(b.locked_until, last_fail + self.window)

    def _evict(self, now: float) -> None:
        """到硬上限时清桶:先删已彻底过期的(锁到期且窗口内无失败);仍超限则逐出最接近过期的,
        直到降回上限内(攻击期桶全'新'也不越界)。仅在插新键且已满时调用,平时零开销。"""
        for k in [k for k, b in self._buckets.items() if self._active_until(b) <= now]:
            del self._buckets[k]
        overflow = len(self._buckets) - _MAX_BUCKETS + 1
        if overflow > 0:
            for k in sorted(self._buckets, key=lambda k: self._active_until(self._buckets[k]))[:overflow]:
                del self._buckets[k]

    def record_failure(self, email: str, ip: str) -> bool:
        """记一次失败。返回 True 表示**本次失败触发了锁定**。"""
        now = time.time()
        with self._lock:
            key = self._key(email, ip)
            if key not in self._buckets and len(self._buckets) >= _MAX_BUCKETS:
                self._evict(now)
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
