"""商品图读取 /media/{key} —— local 直读本地盘,s3 由后端代理对象存储(含私有桶)。

商品图非红线。默认路径:前端 `<img src="{API_BASE}/media/{key}">` → 本端点用存储层
`open(key)` 取流回吐,后端是 local(本地盘)还是 s3(MinIO / OVH Object Storage 私有桶)都通,
不需要公读桶。若将来接了公读 CDN,可让前端置 IMAGE_BACKEND=s3 直连桶、绕过本服务。

前端 `<img src>` 无法携带 Bearer,故此端点**不加鉴权**;安全边界靠:
① key 形状白名单 `img/<uuid32>_<name>`(与 uploads 生成端一致,防路径穿越);
② 该形状**只匹配商品图**,附件是不透明平键(无 `img/` 前缀)不被匹配,故附件不经本端点。
"""
from __future__ import annotations

import mimetypes
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.services.storage import get_attachment_storage

router = APIRouter(prefix="/media", tags=["media"])

# 必须与 uploads.create_upload 生成的 key 形状完全一致:img/<uuid32>_<安全文件名>。
_KEY_RE = re.compile(r"img/[0-9a-f]{32}_[A-Za-z0-9._-]{1,80}")
_CHUNK = 64 * 1024


@router.get("/{key:path}", summary="读商品图(仅 local 后端;生产走公读桶)")
async def read_media(key: str):
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
