"""商品图读取 /api/v1/media/{key}。

业务图片默认不公开:前端用 authFetch 带 Bearer 拉取 blob,本端点校验登录后再经统一
Storage 读取本地盘/MinIO/OVH Object Storage。附件是不透明平键(无 `img/` 前缀),不经本
端点;发票/报关单等仍走 attachments 的业务权限下载。
"""
from __future__ import annotations

import mimetypes
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.core.dependencies import CurrentUser
from app.rbac.guards import block_if_must_change_password
from app.services.storage import get_attachment_storage

router = APIRouter(prefix="/media", tags=["media"])

# 必须与 uploads.create_upload 生成的 key 形状完全一致:img/<uuid32>_<安全文件名>。
_KEY_RE = re.compile(r"img/[0-9a-f]{32}_[A-Za-z0-9._-]{1,80}")
_CHUNK = 64 * 1024


@router.get("/{key:path}", summary="读商品图(需登录)")
async def read_media(
    key: str,
    _current: CurrentUser = Depends(block_if_must_change_password),
):
    if not _KEY_RE.fullmatch(key):
        raise HTTPException(status_code=400, detail="非法 key")

    storage = get_attachment_storage()
    if not storage.exists(key):
        raise HTTPException(status_code=404, detail="图片不存在")

    stream = storage.open(key)
    media_type = mimetypes.guess_type(key)[0] or "application/octet-stream"

    def _iter():
        try:
            while chunk := stream.read(_CHUNK):
                yield chunk
        finally:
            stream.close()

    return StreamingResponse(
        _iter(),
        media_type=media_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )
