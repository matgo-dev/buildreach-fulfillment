"""附件 Service —— 单据扫描件的中转上传 / 鉴权下载 / 关联同步。

安全核心:
- 三层类型校验:扩展名白名单 + 声明 MIME + 内容嗅探(libmagic)允许族匹配;xlsx 再验 ZIP 结构。
- 私有存储,不经公开静态挂载;file_key = 服务端 uuid 平键(不由用户名派生)。
- 下载逐文件 scope:孤儿仅上传者本人在 TTL 内可下;已挂报关 → shipment:read。软删一律不可下。
- 孤儿(未提交表单)TTL + 单用户配额挡增长,无定时清理任务。

归属用直接 FK(customs_declaration_id),非多态 owner;报关场景不预览,故不引 Pillow /
不生成缩略图 / 不做像素炸弹校验(从不 Image.open,恶意图片仅作不透明字节转发)。
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from urllib.parse import quote as url_quote

import magic
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import CurrentUser
from app.core.exceptions import (
    AttachmentOrphanQuotaError,
    AttachmentTooLargeError,
    AttachmentTooManyError,
    AttachmentTypeNotAllowedError,
    AttachmentUnavailableError,
)
from app.db.base import _utcnow
from app.db.models.attachment import Attachment
from app.rbac.constants import Permissions
from app.services.storage import get_attachment_storage
from app.services.upload_pipeline import stream_binary_to_temp

logger = logging.getLogger(__name__)

# ── 允许族(单一源头:扩展名 / 声明 MIME / 嗅探 MIME 同落一处)────────────────
_MAX = settings.ATTACHMENT_MAX_SIZE_BYTES

ALLOWED_FAMILIES: dict[str, dict] = {
    "image/jpeg": {"mimes": {"image/jpeg"}, "ext": {".jpg", ".jpeg"},
                   "canonical": "image/jpeg"},
    "image/png": {"mimes": {"image/png"}, "ext": {".png"}, "canonical": "image/png"},
    "image/webp": {"mimes": {"image/webp"}, "ext": {".webp"}, "canonical": "image/webp"},
    "application/pdf": {"mimes": {"application/pdf"}, "ext": {".pdf"},
                        "canonical": "application/pdf"},
    "spreadsheet_xlsx": {
        "mimes": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                  "application/zip", "application/octet-stream"},
        "ext": {".xlsx"},
        "canonical": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    "spreadsheet_xls": {"mimes": {"application/vnd.ms-excel", "application/octet-stream"},
                        "ext": {".xls"}, "canonical": "application/vnd.ms-excel"},
    "archive_zip": {"mimes": {"application/zip", "application/x-zip-compressed",
                              "application/octet-stream"},
                    "ext": {".zip"}, "canonical": "application/zip"},
    "archive_rar": {"mimes": {"application/x-rar-compressed", "application/vnd.rar",
                              "application/octet-stream"},
                    "ext": {".rar"}, "canonical": "application/x-rar-compressed"},
    "document_docx": {
        "mimes": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                  "application/octet-stream"},
        "ext": {".docx"},
        "canonical": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "document_doc": {"mimes": {"application/msword", "application/octet-stream"},
                     "ext": {".doc"}, "canonical": "application/msword"},
}

_EXT_TO_FAMILY: dict[str, dict] = {}
for _fam in ALLOWED_FAMILIES.values():
    for _ext in _fam["ext"]:
        _EXT_TO_FAMILY[_ext] = _fam
ALLOWED_EXTENSIONS = set(_EXT_TO_FAMILY.keys())


# ── 文件名安全编码(RFC 5987)───────────────────────────────────────────────
_UNSAFE_CHARS = re.compile(r"[\r\n\x00-\x1f/\\]")


def _sanitize_filename(name: str) -> str:
    return _UNSAFE_CHARS.sub("_", name).strip()


def _make_ascii_fallback(name: str) -> str:
    return "".join(c if ord(c) < 128 else "_" for c in name)


def content_disposition(original_filename: str) -> str:
    """强制下载:attachment + ASCII 兜底 filename + UTF-8 原名 filename*(RFC 5987)。"""
    safe = _sanitize_filename(original_filename) or "download"
    ascii_name = _make_ascii_fallback(safe)
    utf8_name = url_quote(safe, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"


# ── 三层类型校验 ────────────────────────────────────────────────────────────
def _verify_xlsx_structure(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            return "[Content_Types].xml" in names and "xl/workbook.xml" in names
    except Exception:
        return False


def validate_file_type(ext: str, declared_mime: str, path: Path, head: bytes) -> str:
    """扩展名 → 族 → 声明 MIME ∈ 族 → 内容嗅探 ∈ 族;xlsx 命中 zip/octet 再验内部结构。
    返回 canonical MIME。任一不过 → 42101。"""
    family = _EXT_TO_FAMILY.get(ext.lower())
    if not family or declared_mime not in family["mimes"]:
        raise AttachmentTypeNotAllowedError()
    sniffed = magic.from_file(str(path), mime=True)
    if sniffed not in family["mimes"]:
        # 短文件 from_file 偏保守,用 head 兜底一次。
        sniffed = magic.from_buffer(head, mime=True)
    if sniffed not in family["mimes"]:
        raise AttachmentTypeNotAllowedError()
    if ext.lower() == ".xlsx" and sniffed in ("application/zip", "application/octet-stream"):
        if not _verify_xlsx_structure(path):
            raise AttachmentTypeNotAllowedError()
    return family["canonical"]


# ── 孤儿配额 ────────────────────────────────────────────────────────────────
async def _check_orphan_quota(db: AsyncSession, user_id: int) -> None:
    """单用户活动孤儿:数量 ≤ QUOTA_COUNT 且合计字节 ≤ QUOTA_BYTES。走孤儿配额偏索引。
    孤儿 = 全部归属 FK 皆 NULL(当前仅 customs_declaration_id 一列)。"""
    count, total = (await db.execute(
        select(func.count(), func.coalesce(func.sum(Attachment.size_bytes), 0))
        .where(Attachment.created_by == user_id,
               Attachment.customs_declaration_id.is_(None),
               Attachment.deleted_at.is_(None)))).one()
    if count >= settings.ATTACHMENT_ORPHAN_QUOTA_COUNT \
            or total >= settings.ATTACHMENT_ORPHAN_QUOTA_BYTES:
        raise AttachmentOrphanQuotaError()


# ── 上传(中转:校验 → 落存储 → 落库)────────────────────────────────────────
async def upload_attachment(db: AsyncSession, *, user_id: int, filename: str,
                            declared_content_type: str,
                            file_stream: BinaryIO) -> Attachment:
    """上传孤儿附件。文件写入不参与 DB 事务:临时文件 → 校验 → storage.save → flush。
    DB 失败 best-effort 删已写文件。"""
    original_filename = _sanitize_filename(filename) or "unnamed"
    ext = PurePosixPath(original_filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise AttachmentTypeNotAllowedError()

    try:
        temp = await stream_binary_to_temp(file_stream, max_size=_MAX, suffix=ext)
    except ValueError:
        raise AttachmentTooLargeError()

    storage = get_attachment_storage()
    file_key = f"{uuid.uuid4().hex}{ext}"
    try:
        canonical = await asyncio.to_thread(
            validate_file_type, ext, declared_content_type, temp.path, temp.head)
        await _check_orphan_quota(db, user_id)
        with open(temp.path, "rb") as src:
            await asyncio.to_thread(storage.save, file_key, src)
        att = Attachment(file_key=file_key, original_filename=original_filename,
                         content_type=canonical, size_bytes=temp.size,
                         customs_declaration_id=None, created_by=user_id)
        db.add(att)
        await db.flush()
        await db.commit()
        await db.refresh(att)
        return att
    except BaseException:
        try:
            storage.delete(file_key)
        except Exception:
            logger.error("上传失败后删除文件也失败: file_key=%s", file_key)
        raise
    finally:
        temp.cleanup()


# ── 下载 scope(逐文件鉴权)──────────────────────────────────────────────────
def can_download(current: CurrentUser, att: Attachment) -> bool:
    """已挂报关 → shipment:read(含 manage)可下;孤儿 → 仅上传者本人且未过 TTL。
    软删附件由调用方按 deleted_at IS NULL 过滤后不可达(F19)。"""
    if att.customs_declaration_id is not None:
        return (Permissions.SHIPMENT_READ in current.permissions
                or Permissions.SHIPMENT_MANAGE in current.permissions)
    if att.created_by != current.id:
        return False
    ttl = timedelta(hours=settings.ATTACHMENT_ORPHAN_TTL_HOURS)
    return _utcnow() - att.created_at <= ttl


async def get_downloadable(db: AsyncSession, current: CurrentUser,
                           attachment_id: int) -> Attachment:
    """取可下载附件(活动 + scope 通过);任一不满足统一 42104(不暴露存在性)。"""
    att = (await db.execute(select(Attachment).where(
        Attachment.id == attachment_id, Attachment.deleted_at.is_(None)))).scalar_one_or_none()
    if att is None or not can_download(current, att):
        raise AttachmentUnavailableError()
    return att


# ── 删孤儿(误传纠错;仅上传者本人,仅孤儿)──────────────────────────────────
async def delete_orphan(db: AsyncSession, *, user_id: int, attachment_id: int) -> None:
    att = (await db.execute(select(Attachment).where(
        Attachment.id == attachment_id, Attachment.deleted_at.is_(None)))).scalar_one_or_none()
    if att is None or att.customs_declaration_id is not None or att.created_by != user_id:
        raise AttachmentUnavailableError()
    att.deleted_at = datetime.now(timezone.utc)
    await db.commit()


# ── 关联同步(报关 POST/PATCH 内调用,全量替换语义)──────────────────────────
async def sync_attachments(db: AsyncSession, *, user_id: int, declaration_id: int,
                           attachment_ids: list[int]) -> list[int]:
    """把 declaration 的附件集设为 attachment_ids(全量替换)。返回被移出(软删)的 id。
    校验谓词(防锁死协作编辑):
    - 保留项(已属本记录):仅要求未删,不查上传者/TTL(同事可保留同事传的附件);
    - 新增项(孤儿):必须本人 + 未过 TTL;
    - 其它(已属他单/已删/不存在):42104。
    移出 = 软删(可经 DB 恢复,物理文件保留),不退回孤儿。"""
    if len(attachment_ids) > settings.ATTACHMENT_MAX_PER_OWNER:
        raise AttachmentTooManyError()
    now = _utcnow()
    ttl = timedelta(hours=settings.ATTACHMENT_ORPHAN_TTL_HOURS)
    id_set = set(attachment_ids)

    for att_id in attachment_ids:
        att = (await db.execute(select(Attachment).where(
            Attachment.id == att_id,
            Attachment.deleted_at.is_(None)))).scalar_one_or_none()
        if att is None:
            raise AttachmentUnavailableError()
        if att.customs_declaration_id == declaration_id:
            continue  # 保留项
        if att.customs_declaration_id is not None:
            raise AttachmentUnavailableError()  # 已属他单
        if att.created_by != user_id or now - att.created_at > ttl:
            raise AttachmentUnavailableError()  # 非本人孤儿 / 已过 TTL
        att.customs_declaration_id = declaration_id

    removed: list[int] = []
    existing = (await db.execute(select(Attachment).where(
        Attachment.customs_declaration_id == declaration_id,
        Attachment.deleted_at.is_(None)))).scalars().all()
    for old in existing:
        if old.id not in id_set:
            old.deleted_at = datetime.now(timezone.utc)
            removed.append(old.id)
    return removed


async def cascade_soft_delete(db: AsyncSession, declaration_id: int) -> list[int]:
    """报关记录软删时级联软删其附件;返回被软删的附件 id(供审计 extra)。"""
    atts = (await db.execute(select(Attachment).where(
        Attachment.customs_declaration_id == declaration_id,
        Attachment.deleted_at.is_(None)))).scalars().all()
    now = datetime.now(timezone.utc)
    ids = []
    for att in atts:
        att.deleted_at = now
        ids.append(att.id)
    return ids


async def list_for_declaration(db: AsyncSession, declaration_id: int) -> list[Attachment]:
    return list((await db.execute(select(Attachment).where(
        Attachment.customs_declaration_id == declaration_id,
        Attachment.deleted_at.is_(None)).order_by(Attachment.id))).scalars().all())
