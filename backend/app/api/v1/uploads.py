"""图片直传路由 /api/v1/uploads(商品图,非红线,守 product:manage —— 能改商品才能传图)。

两步走(前端一套代码,local/s3 通用):
1. POST ""  body {filename, content_type} → 生成 key → Storage.create_upload → {key, upload_url, method}
2. 按 upload_url 传文件:
   - s3(OSS):前端直传 presigned URL,不经本服务。
   - local:PUT /{key} 本服务接收落盘(仅 local 后端提供;s3 后端该端点不适用)。
"""
from __future__ import annotations

import re
import uuid
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.rbac.constants import Permissions
from app.rbac.guards import require_permission
from app.services.storage import get_attachment_storage

router = APIRouter(prefix="/uploads", tags=["uploads"])

# key 形状必须与 create_upload 生成的完全一致,PUT 端点据此拒绝穿越/越权覆盖。
_KEY_RE = re.compile(r"img/[0-9a-f]{32}_[A-Za-z0-9._-]{1,80}")
# 仅允许光栅图片;显式排除 image/svg+xml(可执行脚本 → 存储型 XSS)。
_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
# 单图硬上限 20MB(前端另有软限;后端是最后防线,防大文件打爆内存/存储)。
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class CreateUploadIn(BaseModel):
    filename: str = Field(..., min_length=1)
    content_type: str = Field(..., min_length=1)


@router.post("", summary="生成上传直传描述(商品图)")
async def create_upload(
    body: CreateUploadIn,
    _current: CurrentUser = Depends(require_permission(Permissions.PRODUCT_MANAGE)),
):
    if body.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="仅支持 jpeg/png/webp/gif 图片")

    # 净化文件名:只取 basename,剥除路径段,再收窄到白名单字符集 —
    # 保证生成的 key 必然匹配 PUT 端点的 _KEY_RE 校验(含中文/空格等文件名)。
    basename = Path(body.filename).name or "file"
    safe_name = (re.sub(r"[^A-Za-z0-9._-]", "_", basename) or "file")[:80]
    key = f"img/{uuid.uuid4().hex}_{safe_name}"
    assert _KEY_RE.fullmatch(key), f"generated upload key failed shape check: {key}"
    result = get_attachment_storage().create_upload(key, body.content_type)
    return success(result)


@router.put("/{key:path}", summary="本地后端接收直传(仅 STORAGE_BACKEND=local 提供)")
async def receive_upload(
    key: str,
    request: Request,
    _current: CurrentUser = Depends(require_permission(Permissions.PRODUCT_MANAGE)),
):
    if settings.STORAGE_BACKEND != "local":
        raise HTTPException(
            status_code=405, detail="该后端走对象存储直传,不经本端点")
    if not _KEY_RE.fullmatch(key):
        raise HTTPException(status_code=400, detail="非法上传 key")
    # 先看 Content-Length 快速拒;再按实读字节兜底(头可伪造)。
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="图片超过 20MB 上限")
    body = await request.body()
    if len(body) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="图片超过 20MB 上限")
    get_attachment_storage().save(key, BytesIO(body))
    return success({"key": key})
