"""附件上传管线助手:有界流式落临时盘 + 嗅探 head 缓存。

绝不 `await request.body()` / 一次性读整段(可伪造省略 Content-Length 的无界载荷 → OOM);
逐块读、累计超上限即拒。临时目录走系统 tmp(恒可写、进程退出自动清、尊重 TMPDIR),
不放源码树下(非 root 容器不可写会 500)。
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

UPLOAD_CHUNK_SIZE = 1024 * 1024
SNIFF_BYTES = 8192
_TMP_UPLOAD_DIR = Path(tempfile.gettempdir()) / "fulfillment_uploads"


@dataclass(slots=True)
class TempUpload:
    path: Path
    size: int
    head: bytes  # 前 SNIFF_BYTES 字节,供 libmagic 嗅探(免二次读盘)

    def cleanup(self) -> None:
        self.path.unlink(missing_ok=True)


def _create_temp_path(suffix: str) -> tuple[int, Path]:
    _TMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="upload_", suffix=suffix, dir=_TMP_UPLOAD_DIR)
    return fd, Path(name)


def _append_head(head: bytearray, chunk: bytes) -> None:
    if len(head) >= SNIFF_BYTES:
        return
    head.extend(chunk[: SNIFF_BYTES - len(head)])


async def stream_binary_to_temp(stream: BinaryIO, *, max_size: int,
                                suffix: str = "") -> TempUpload:
    """把同步 BinaryIO(UploadFile.file)有界流式写入临时文件;超 max_size 抛 ValueError。
    读/写/fsync 全走 to_thread,不阻塞事件循环。"""
    fd, path = _create_temp_path(suffix)
    head = bytearray()
    total = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = await asyncio.to_thread(stream.read, UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_size:
                    raise ValueError("upload too large")
                _append_head(head, chunk)
                await asyncio.to_thread(out.write, chunk)
            await asyncio.to_thread(out.flush)
            await asyncio.to_thread(os.fsync, out.fileno())
        return TempUpload(path=path, size=total, head=bytes(head))
    except BaseException:
        path.unlink(missing_ok=True)
        raise
