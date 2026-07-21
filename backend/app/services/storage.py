"""统一 Storage 适配层 — 业务只认 file_key,不碰文件在本地还是 OSS。

LocalDiskStorage(本地)/ S3Storage(MinIO 本地 · 生产 S3 兼容云对象存储);
由 settings.STORAGE_BACKEND 驱动的工厂 get_attachment_storage() 选择实现,业务不动。
"""
from __future__ import annotations

import logging
import os
import shutil
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol, runtime_checkable

import boto3
from botocore.config import Config as _BotoConfig

from app.core.config import settings

logger = logging.getLogger(__name__)


class StorageKeyError(ValueError):
    """file_key 未通过安全校验(空 / 绝对路径 / `..` 穿越 / 反斜杠 / 控制字符)。
    落到最强层:本地盘 key→路径解析前**显式拒绝**,不静默截断成 basename(截断会把
    `img/x` 悄悄打平、把穿越悄悄吞掉,是「掩盖而非拒绝」)。"""


def validate_file_key(key: str) -> str:
    """校验 file_key 为安全的相对存储键并返回。允许内部 `/` 作为子目录段(商品图用
    `img/<uuid>`),但拒绝一切穿越向量。附件服务生成的是不透明 uuid 平键(无 `/`),
    此校验对其恒通过;对外部/历史来源的 key 提供纵深防御。

    拒绝:空串、`\\`(反斜杠)、控制字符/空字节、绝对路径、任何 `.`/`..` 段、
    解析后逃逸出相对根的键。"""
    if not key or not isinstance(key, str):
        raise StorageKeyError("empty file_key")
    if "\\" in key or any(ord(c) < 0x20 for c in key):
        raise StorageKeyError(f"illegal characters in file_key: {key!r}")
    pure = PurePosixPath(key)
    if pure.is_absolute():
        raise StorageKeyError(f"absolute file_key not allowed: {key!r}")
    parts = pure.parts
    if not parts or any(p in ("", ".", "..") for p in parts):
        raise StorageKeyError(f"path traversal in file_key: {key!r}")
    # 要求规范形式:拒绝 `./a`、`a/./b`、`a//b`、`trailing/` 等非规范键(虽解析安全,但存进
    # DB 的 key 必须无歧义、与解析路径一一对应),防「同一文件多种键表达」。
    if str(pure) != key:
        raise StorageKeyError(f"non-canonical file_key: {key!r}")
    return key


@runtime_checkable
class Storage(Protocol):
    """存储协议:业务层唯一入口,从不直接 import oss2 或 open(本地路径)。"""

    def save(self, file_key: str, stream: BinaryIO) -> None:
        """将流写入存储。"""
        ...

    def open(self, file_key: str) -> BinaryIO:
        """返回可读二进制流(不是本地路径)。"""
        ...

    def delete(self, file_key: str) -> None:
        """删除文件(best-effort)。"""
        ...

    def exists(self, file_key: str) -> bool:
        """文件是否存在。"""
        ...

    def public_url(self, key: str) -> str:
        """公开资产 URL(商品图,走 CDN);敏感件不用。"""
        ...

    def build_url(self, key: str, size: int | None = None) -> str:
        """展示用 URL,size 给定时请求缩略(OSS 走 x-oss-process;本地存储层不做变换)。"""
        ...

    def create_upload(self, key: str, content_type: str) -> dict:
        """生成前端直传描述:{key, upload_url, method}。"""
        ...


class LocalDiskStorage:
    """本地磁盘存储 — 附件私有目录,不经 /static 公开。"""

    def __init__(self, base_dir: str | Path) -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def _path(self, file_key: str) -> Path:
        # 显式拒绝穿越(见 validate_file_key),不静默截断成 basename。合法子目录段(如
        # 商品图 img/<uuid>)保留;附件是不透明 uuid 平键。解析后再兜一层「必在 base 内」。
        safe_key = validate_file_key(file_key)
        target = (self._base / safe_key).resolve()
        base = self._base.resolve()
        if base != target and base not in target.parents:
            raise StorageKeyError(f"file_key escapes storage root: {file_key!r}")
        return target

    def save(self, file_key: str, stream: BinaryIO) -> None:
        target = self._path(file_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        try:
            with open(tmp, "wb") as f:
                shutil.copyfileobj(stream, f)
                f.flush()
                os.fsync(f.fileno())
            tmp.rename(target)
        except BaseException:
            # 写失败,清理临时文件
            tmp.unlink(missing_ok=True)
            raise

    def open(self, file_key: str) -> BinaryIO:
        target = self._path(file_key)
        if not target.is_file():
            raise FileNotFoundError(f"Storage file not found: {file_key}")
        return open(target, "rb")

    def delete(self, file_key: str) -> None:
        target = self._path(file_key)
        target.unlink(missing_ok=True)

    def exists(self, file_key: str) -> bool:
        return self._path(file_key).is_file()

    def public_url(self, key: str) -> str:
        return f"{settings.IMAGE_PATH_PREFIX}/{key}"

    def build_url(self, key: str, size: int | None = None) -> str:
        # 本地存储零图像处理:忽略 size,浏览器降采样兜底。
        # 已知限制(仅本地 dev):save() 把 key 打平成 basename(_path 用 Path(key).name),
        # 此处却返回带 'img/' 前缀的 /media/{key},且 /media 未挂静态路由 —— 本地传的图当前
        # 预览不出来。生产走 S3Storage(public_url 前缀一致),无此问题。待商品图上传前端
        # 落地时一并修(挂 /media 静态路由或 save 保留 key 路径),不留在私有 ledger。
        return f"/media/{key}"

    def create_upload(self, key: str, content_type: str) -> dict:
        # 本地后端无对象存储直传能力:指回本服务的 PUT 接收端点。
        return {"key": key, "upload_url": f"/api/v1/uploads/{key}", "method": "PUT"}


class S3Storage:
    """S3 兼容对象存储 —— 本地 MinIO / 生产 S3 兼容云对象存储。"""

    def __init__(self, *, endpoint_url: str, region: str, access_key: str,
                 secret_key: str, bucket: str, public_base_url: str = "") -> None:
        self._bucket = bucket
        self._public_base = public_base_url.rstrip("/")
        self._client = boto3.client(
            "s3", endpoint_url=endpoint_url or None, region_name=region,
            aws_access_key_id=access_key, aws_secret_access_key=secret_key,
            config=_BotoConfig(signature_version="s3v4"))

    def save(self, file_key: str, stream: BinaryIO) -> None:
        self._client.upload_fileobj(stream, self._bucket, file_key)

    def open(self, file_key: str) -> BinaryIO:
        obj = self._client.get_object(Bucket=self._bucket, Key=file_key)
        return BytesIO(obj["Body"].read())

    def delete(self, file_key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=file_key)

    def exists(self, file_key: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            self._client.head_object(Bucket=self._bucket, Key=file_key)
            return True
        except ClientError:
            return False

    def public_url(self, key: str) -> str:
        return f"{self._public_base}/{key}" if self._public_base else key

    def build_url(self, key: str, size: int | None = None) -> str:
        # 存储层实时改尺寸:OSS x-oss-process 拼参数,不落地多份。
        base = self.public_url(key)
        if size:
            return f"{base}?x-oss-process=image/resize,w_{size}"
        return base

    def create_upload(self, key: str, content_type: str) -> dict:
        # 前端直传:PUT 预签名 URL,免经后端中转。
        upload_url = self._client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=300,
        )
        return {"key": key, "upload_url": upload_url, "method": "PUT"}


# ── 单例(启动时初始化,按 settings.STORAGE_BACKEND 选择实现) ──

_PRIVATE_UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / "private_uploads" / "attachments"

_attachment_storage: "Storage | None" = None


def get_attachment_storage() -> "Storage":
    """获取附件存储单例(懒初始化)。local(默认)/ s3(MinIO・OSS)。"""
    global _attachment_storage
    if _attachment_storage is None:
        if settings.STORAGE_BACKEND == "s3":
            _attachment_storage = S3Storage(
                endpoint_url=settings.S3_ENDPOINT_URL, region=settings.S3_REGION,
                access_key=settings.S3_ACCESS_KEY, secret_key=settings.S3_SECRET_KEY,
                bucket=settings.S3_BUCKET, public_base_url=settings.S3_PUBLIC_BASE_URL)
        else:
            _attachment_storage = LocalDiskStorage(_PRIVATE_UPLOADS_DIR)
    return _attachment_storage
