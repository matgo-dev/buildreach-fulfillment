"""附件路由 /api/v1/attachments。M0 基座:最小上传端点,仅验证「能传对象存储」。

不落 DB 记录、不做类型/大小校验 —— 那些是业务层(履约单据附件)的事,本期只证存储薄接口打通。
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, UploadFile

from app.core.dependencies import CurrentUser, get_current_user
from app.core.exceptions import success
from app.services.storage import get_attachment_storage

router = APIRouter(prefix="/attachments", tags=["attachments"])


@router.post("", summary="上传附件(最小实现,返回 file_key)")
async def upload_attachment(
    file: UploadFile = File(...),
    _user: CurrentUser = Depends(get_current_user),
):
    file_key = f"{uuid.uuid4().hex}_{file.filename}"
    get_attachment_storage().save(file_key, file.file)
    return success({"file_key": file_key})
