from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampUpdateMixin


class Attachment(Base, TimestampUpdateMixin, SoftDeleteMixin):
    """单据扫描件的文件注册(全局基建表)。首个消费者 = 报关记录。

    走后端中转上传(非对象存储直传),三层类型校验(扩展名 + 声明 MIME + libmagic 嗅探)。
    file_key = 服务端生成的不透明随机键(uuid4 系),UNIQUE;**严禁由用户文件名派生**;
    Storage 层 key→路径解析带穿越守卫。归属用直接 FK 列(不用多态 owner_type/owner_id,
    遵本仓「每引用列有 FK」铁律)。

    孤儿定义 = **所有归属 FK 均为 NULL**(当前仅 customs_declaration_id 一列)。孤儿 = 已上传
    未提交表单的临时文件,由配额(每用户 ≤20/≤100MB)+ 72h TTL 挡增长,无定时清理任务。
    第二消费域出现时 = 加平行 nullable FK 列 + 同步扩孤儿谓词/配额偏索引/TTL 逻辑为「全 NULL」,
    **不回头改多态**。无红线字段(元数据本身;文件内容是运营录入物,后端不解析)。
    """
    __tablename__ = "attachments"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="ck_attachments_size_positive"),
        # 孤儿配额偏索引:精确命中「某用户的活动孤儿」谓词,不随其历史已归属附件增长。
        # 加平行归属 FK 列时须同步把谓词扩成「全部归属列皆 NULL」。
        Index("ix_attachments_orphan_quota", "created_by",
              postgresql_where=text(
                  "customs_declaration_id IS NULL AND deleted_at IS NULL")),
        # 显式命名与迁移 0031 一致(index=True 默认名会带 _id 尾,漂移会让 autogenerate 报虚假 diff)。
        Index("ix_attachments_customs_declaration", "customs_declaration_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 存储键(不透明随机;业务只认 key 不碰路径)。
    file_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    # 原始文件名(仅展示 / 下载头用,不进存储路径)。
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # 实测 MIME(嗅探结果为准)。
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # 文件字节数(BIGINT;上限走应用层配置,不落 CHECK)。
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 归属报关记录(NULL = 孤儿)。RESTRICT:有附件的报关记录不可硬删穿透(级联软删走 service)。
    customs_declaration_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("customs_declarations.id", ondelete="RESTRICT"),
        nullable=True)
    # 上传者 = 创建者(不另设 uploaded_by,单一源头);FK RESTRICT + 单列索引。
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
