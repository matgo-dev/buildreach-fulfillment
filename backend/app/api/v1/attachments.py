"""附件端点 /api/v1/attachments —— 中转上传 + 逐文件鉴权下载 + 删孤儿。

上传/删孤儿守 shipment:manage(当前唯一消费域=报关;新消费者出现时改为按域集合)。
下载仅需登录,scope 在 service 逐文件判(孤儿=上传者本人/TTL;已挂报关=shipment:read)。
下载恒强制 attachment + nosniff,不提供 inline/preview。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user
from app.core.exceptions import AttachmentUnavailableError, success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_permission
from app.schemas.attachment import AttachmentPublic
from app.services import attachment_service
from app.services.storage import get_attachment_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/attachments", tags=["attachments"])

_MANAGE = Depends(require_permission(Permissions.SHIPMENT_MANAGE))


@router.post("", summary="上传附件(孤儿;三层类型校验 + 大小 + 孤儿配额)")
async def upload(file: UploadFile = File(...), current: CurrentUser = _MANAGE,
                 db: AsyncSession = Depends(get_db)):
    att = await attachment_service.upload_attachment(
        db, user_id=current.id, filename=file.filename or "unnamed",
        declared_content_type=file.content_type or "application/octet-stream",
        file_stream=file.file)
    return success(AttachmentPublic.build(att).model_dump())


@router.get("/{attachment_id}/download", summary="鉴权流式下载(强制下载 + nosniff)")
async def download(attachment_id: int, current: CurrentUser = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)):
    att = await attachment_service.get_downloadable(db, current, attachment_id)
    storage = get_attachment_storage()
    try:
        stream = storage.open(att.file_key)
    except FileNotFoundError:
        logger.error("附件存储缺失: attachment_id=%d file_key=%s", att.id, att.file_key)
        raise AttachmentUnavailableError()
    return StreamingResponse(
        stream, media_type=att.content_type,
        headers={
            "Content-Disposition": attachment_service.content_disposition(att.original_filename),
            "X-Content-Type-Options": "nosniff",
            "Content-Length": str(att.size_bytes),
        })


@router.delete("/{attachment_id}", summary="删孤儿附件(误传纠错;仅上传者本人,仅未关联)")
async def delete(attachment_id: int, current: CurrentUser = _MANAGE,
                 db: AsyncSession = Depends(get_db)):
    await attachment_service.delete_orphan(db, user_id=current.id, attachment_id=attachment_id)
    return success()
