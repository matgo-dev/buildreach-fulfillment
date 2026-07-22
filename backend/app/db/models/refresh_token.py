from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_UUID4_HEX_LEN = 32
_SHA256_HEX_LEN = 64


class RefreshToken(Base):
    """Refresh token 家族账本 —— 服务端记账,支撑轮换作废 + 重放检测 + 单会话吊销。

    一次登录开一个 family(token 家族);refresh 轮换在同族内派生后继并把父行标 `used_at`。
    重放(已 used 的父 token 在宽限窗外再现)→ 撤整族;logout → 撤本族。
    与 `users.token_version` 分工:tv = 改密/封号的全局总闸(一刀切所有会话);
    family = 单会话精确掐断,两层各管各、非二选一。

    安全:只存 jti 的 sha256 十六进制,不存 token 原文(库泄漏 ≠ token 泄漏)。
    无红线字段(无成本/供应商/售价)。过期行惰性清理(有界小表,~几千行)。

    `issued_at` 即本行创建时刻(不再叠 created_at);`user_id` 即创建人=持有人
    (不叠 created_by,归属唯一);行状态由 used_at/revoked_at 显式列表达,无 updated_at。
    """
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        CheckConstraint("expires_at > issued_at",
                        name="ck_refresh_tokens_expiry_after_issue"),
        # 时序:消费/撤销时刻不得早于签发(DB 兜底,脏行会喂错宽限窗计算)。
        CheckConstraint("used_at IS NULL OR used_at >= issued_at",
                        name="ck_refresh_tokens_used_after_issue"),
        CheckConstraint("revoked_at IS NULL OR revoked_at >= issued_at",
                        name="ck_refresh_tokens_revoked_after_issue"),
        # 轮换恒同时写 used_at + replaced_by;配对 CHECK 挡住「标 used 漏写后继」半态脏行。
        CheckConstraint("(used_at IS NULL) = (replaced_by_jti_hash IS NULL)",
                        name="ck_refresh_tokens_used_replaced_paired"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 持有人。RESTRICT:有 token 记录的用户不可硬删(先撤 token / 走注销)。FK 铁律全量索引。
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    # 一次登录一个家族 id(uuid4 hex,32);family 维度撤销(登出/重放)的查询列 → 索引。
    family_id: Mapped[str] = mapped_column(String(_UUID4_HEX_LEN), nullable=False, index=True)
    # 本 refresh token jti 的 sha256 十六进制(64)。refresh 查库的主路径;唯一(索引即唯一约束)。
    jti_hash: Mapped[str] = mapped_column(String(_SHA256_HEX_LEN), nullable=False, unique=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 惰性清理谓词(DELETE WHERE expires_at < now)走索引。
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True)
    # 轮换消费时刻(父行被换掉的时点);宽限窗从此刻起算、不因窗内重放而延后。NULL = 未用。
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # 家族被撤时刻(重放检测 / 登出 / 吊销)。NULL = 活动。
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # 轮换出的后继 jti_hash(链路追溯)。NULL = 未轮换。自引用 FK 保证不指向不存在的行;
    # 惰性清理按 expires_at 先删父后删子,SET NULL 实际不会触发,仅作完整性兜底。
    replaced_by_jti_hash: Mapped[str | None] = mapped_column(
        String(_SHA256_HEX_LEN),
        ForeignKey("refresh_tokens.jti_hash", ondelete="SET NULL"),
        nullable=True)
