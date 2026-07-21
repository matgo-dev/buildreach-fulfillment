"""附件 Service —— 单据扫描件的中转上传 / 鉴权下载 / 关联同步。

安全核心:
- 三层类型校验:扩展名白名单 + 声明 MIME + 内容嗅探(libmagic)允许族匹配;xlsx 再验 ZIP 结构。
- 私有存储,不经公开静态挂载;file_key = 服务端 uuid 平键(不由用户名派生)。
- 下载逐文件 scope:孤儿仅上传者本人在 TTL 内可下;已挂报关 → shipment:read。软删一律不可下。
- 孤儿(未提交表单)TTL + 单用户配额(含本次上传)挡增长;过期孤儿在上传时惰性回收
  (软删 + best-effort 删物理文件),不设定时清理任务。

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
# 含 `"`:文件名进 Content-Disposition 的 quoted-string,双引号不清会产出畸形头。
_UNSAFE_CHARS = re.compile(r"[\r\n\x00-\x1f/\\\"]")


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


# ── 孤儿配额 + 惰性回收 ─────────────────────────────────────────────────────
async def _reap_expired_orphans(db: AsyncSession, user_id: int) -> None:
    """惰性回收本人**过期**孤儿(软删 + best-effort 删物理文件)。无定时任务的替代口:
    上传时顺手清。过期孤儿不可下载/不可认领,留着只会永久占配额把人锁死(42103)、
    物理文件无界堆积。行数有界(≤ 配额数),走孤儿配额偏索引。skip_locked:正被
    sync_attachments 认领中的行跳过(认领会重校验 TTL,不会把过期的挂上)。
    物理删失败或本事务回滚都只留下「活动行指缺失/残留文件」,过期孤儿本就不可达,
    下次上传重扫自愈。"""
    cutoff = _utcnow() - timedelta(hours=settings.ATTACHMENT_ORPHAN_TTL_HOURS)
    rows = (await db.execute(select(Attachment).where(
        Attachment.created_by == user_id,
        Attachment.customs_declaration_id.is_(None),
        Attachment.deleted_at.is_(None),
        Attachment.created_at < cutoff).with_for_update(skip_locked=True))).scalars().all()
    if not rows:
        return
    storage = get_attachment_storage()
    now = datetime.now(timezone.utc)
    for att in rows:
        att.deleted_at = now
        try:
            await asyncio.to_thread(storage.delete, att.file_key)
        except Exception:
            logger.error("过期孤儿物理文件删除失败: file_key=%s", att.file_key)


async def _check_orphan_quota(db: AsyncSession, user_id: int, incoming_bytes: int) -> None:
    """单用户活动孤儿(含本次上传):数量 ≤ QUOTA_COUNT 且合计字节 ≤ QUOTA_BYTES。
    走孤儿配额偏索引。孤儿 = 全部归属 FK 皆 NULL(当前仅 customs_declaration_id 一列)。
    字节配额按「已有 + 本次」判,否则 99MB 存量还能再传一整个 50MB 突破上限。"""
    count, total = (await db.execute(
        select(func.count(), func.coalesce(func.sum(Attachment.size_bytes), 0))
        .where(Attachment.created_by == user_id,
               Attachment.customs_declaration_id.is_(None),
               Attachment.deleted_at.is_(None)))).one()
    if count + 1 > settings.ATTACHMENT_ORPHAN_QUOTA_COUNT \
            or total + incoming_bytes > settings.ATTACHMENT_ORPHAN_QUOTA_BYTES:
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
        temp = await stream_binary_to_temp(
            file_stream, max_size=settings.ATTACHMENT_MAX_SIZE_BYTES, suffix=ext)
    except ValueError:
        raise AttachmentTooLargeError()

    storage = get_attachment_storage()
    file_key = f"{uuid.uuid4().hex}{ext}"
    try:
        canonical = await asyncio.to_thread(
            validate_file_type, ext, declared_content_type, temp.path, temp.head)
        await _reap_expired_orphans(db, user_id)
        await _check_orphan_quota(db, user_id, temp.size)
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
    # 行锁:与 sync_attachments 的并发认领互斥(防「删的同时被挂上报关」两边都成功)。
    att = (await db.execute(select(Attachment).where(
        Attachment.id == attachment_id, Attachment.deleted_at.is_(None))
        .with_for_update())).scalar_one_or_none()
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

    for att_id in sorted(id_set):
        # 行锁认领:校验(孤儿/本人/TTL)与改指 customs_declaration_id 之间不留窗口,
        # 防同一孤儿被并发挂到两条报关记录(不同柜 → 柜头锁不互斥)后一方静默改指。
        # 锁序:柜头(调用方已持)→ 附件行按 id 升序(并发重叠集不死锁),附件恒为叶子锁。
        # 上限 ≤10,逐行锁有界。
        att = (await db.execute(select(Attachment).where(
            Attachment.id == att_id,
            Attachment.deleted_at.is_(None)).with_for_update())).scalar_one_or_none()
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
