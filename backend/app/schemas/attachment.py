"""附件 DTO — 对外只下发展示/下载所需,不含 created_by 等内部标识。"""
from __future__ import annotations

from pydantic import BaseModel


class AttachmentPublic(BaseModel):
    """对外附件信息(元数据 + 鉴权下载 URL;无缩略图 —— 报关场景不预览)。"""
    id: int
    original_filename: str
    content_type: str
    size_bytes: int
    download_url: str

    @classmethod
    def build(cls, att) -> "AttachmentPublic":
        return cls(
            id=att.id,
            original_filename=att.original_filename,
            content_type=att.content_type,
            size_bytes=att.size_bytes,
            download_url=f"/api/v1/attachments/{att.id}/download",
        )
