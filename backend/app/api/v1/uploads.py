"""图片直传路由 /api/v1/uploads(商品图,非红线,守 catalog:manage —— 能改商品才能传图)。

两步走(前端一套代码,local/s3 通用):
1. POST ""  body {filename, content_type} → 生成 key → Storage.create_upload → {key, upload_url, method}
2. 按 upload_url 传文件:
   - s3(OSS):前端直传 presigned URL,不经本服务。
   - local:PUT /{key} 本服务接收落盘(仅 local 后端提供;s3 后端该端点不适用)。
"""
from __future__ import annotations

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


class CreateUploadIn(BaseModel):
    filename: str = Field(..., min_length=1)
    content_type: str = Field(..., min_length=1)


@router.post("", summary="生成上传直传描述(商品图)")
async def create_upload(
    body: CreateUploadIn,
    _current: CurrentUser = Depends(require_permission(Permissions.CATALOG_MANAGE)),
):
    # 净化文件名:只取 basename,剥除路径段,避免注入对象存储 key 命名空间。
    safe_name = Path(body.filename).name or "file"
    key = f"img/{uuid.uuid4().hex}_{safe_name}"
    result = get_attachment_storage().create_upload(key, body.content_type)
    return success(result)


@router.put("/{key:path}", summary="本地后端接收直传(仅 STORAGE_BACKEND=local 提供)")
async def receive_upload(
    key: str,
    request: Request,
    _current: CurrentUser = Depends(require_permission(Permissions.CATALOG_MANAGE)),
):
    if settings.STORAGE_BACKEND != "local":
        raise HTTPException(
            status_code=405, detail="该后端走对象存储直传,不经本端点")
    body = await request.body()
    get_attachment_storage().save(key, BytesIO(body))
    return success({"key": key})
