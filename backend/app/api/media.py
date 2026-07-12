"""商品图公开读取 /media/{key} —— **仅 STORAGE_BACKEND=local 提供**。

DESIGN §8:商品图非红线,展示 URL 由存储层 `build_url` 给出;local 后端返回 `/media/{key}`。
生产走对象存储公读桶(S3/OSS),`<img>` 直连桶,不经本服务(本端点返回 404)。

本地开发下前端 `<img src>` 无法携带 Bearer,故此端点**不加鉴权**;安全边界靠:
① 仅 local 后端启用(生产不可达);② key 形状白名单(与 uploads 生成端一致,防路径穿越)。
"""
from __future__ import annotations

import mimetypes
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.services.storage import get_attachment_storage

router = APIRouter(prefix="/media", tags=["media"])

# 必须与 uploads.create_upload 生成的 key 形状完全一致:img/<uuid32>_<安全文件名>。
_KEY_RE = re.compile(r"img/[0-9a-f]{32}_[A-Za-z0-9._-]{1,80}")
_CHUNK = 64 * 1024


@router.get("/{key:path}", summary="读商品图(仅 local 后端;生产走公读桶)")
async def read_media(key: str):
    if settings.STORAGE_BACKEND != "local":
        raise HTTPException(status_code=404, detail="对象存储走公读桶,不经本端点")
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
        headers={"Cache-Control": "public, max-age=3600"},
    )
