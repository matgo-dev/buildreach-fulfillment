from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_UUID4_HEX_LEN = 32


class RefreshTokenFamily(Base):
    """Refresh token 家族(＝一次登录开的一个会话)的**组级承载行**。

    「家族已撤」是族级事实,必须有族级的可锁承载行,不能散落在 N 个成员 token 行上——
    否则撤族(set-based 扫成员行)与并发 refresh 派生新成员之间存在幻影窗口:新出生的
    成员行是撤族语句快照外的 phantom,漏撤即逃逸,击穿「整族全撤 / logout 服务端吊销」。
    (根因见错题集 A8:组级不变量 ≠ 成员级锁。)

    撤族 = 锁本行 `FOR UPDATE` / 原子 UPDATE `revoked_at`(O(1) 单行);refresh 派生成员前
    先锁本行 → INSERT 与撤族串行,无幻影。成员的存活判定统一读 `family.revoked_at`。

    与 `users.token_version` 分工:tv = 改密/封号的全局总闸(一刀切所有族);
    family = 单会话精确掐断,两层各管各、非二选一。

    空族(成员全过期被清)由登录路径惰性清理一并删除(有界)。
    """
    __tablename__ = "refresh_token_families"
    __table_args__ = (
        CheckConstraint("revoked_at IS NULL OR revoked_at >= created_at",
                        name="ck_refresh_token_families_revoked_after_create"),
    )

    # 家族 id = uuid4 hex(32);登录时生成,成员 token 行 FK 指向它。
    id: Mapped[str] = mapped_column(String(_UUID4_HEX_LEN), primary_key=True)
    # 持有人。RESTRICT:有活会话的用户不可硬删(先撤会话 / 走注销)。FK 铁律全量索引。
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 家族被撤时刻(登出 / 重放检测 / 吊销)。NULL = 活动。族级单一源头,不散在成员行上。
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
