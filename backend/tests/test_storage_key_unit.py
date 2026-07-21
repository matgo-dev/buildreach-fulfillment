"""storage.py 加固单测:file_key 显式拒绝穿越(替代静默截 basename),LocalDiskStorage 全方法
路径守卫。契约 §1.2 F18:file_key 不透明随机 + 穿越守卫;save/open/delete/exists 全覆盖。
"""
import io

import pytest

from app.services.storage import (
    LocalDiskStorage,
    StorageKeyError,
    validate_file_key,
)

# 合法键:不透明平键(附件用)+ 安全子目录段(商品图 img/<uuid>)。
_VALID = [
    "a1b2c3d4.pdf",
    "0123456789abcdef0123456789abcdef.png",
    "img/0123456789abcdef0123456789abcdef_name.jpg",
]
# 非法键:空 / 绝对 / .. 穿越 / 反斜杠 / 控制字符 / 单点段 / 首尾斜杠导致空段。
_INVALID = [
    "", "/etc/passwd", "../secret", "a/../../b", "img/../../etc/passwd",
    "a\\b.pdf", "a\x00b.pdf", "./a.pdf", "a/./b", "/leading", "trailing/",
]


@pytest.mark.parametrize("key", _VALID)
def test_validate_accepts_safe_keys(key):
    assert validate_file_key(key) == key


@pytest.mark.parametrize("key", _INVALID)
def test_validate_rejects_traversal(key):
    with pytest.raises(StorageKeyError):
        validate_file_key(key)


def test_localdisk_roundtrip_and_subdir(tmp_path):
    st = LocalDiskStorage(tmp_path)
    st.save("img/deadbeef_name.png", io.BytesIO(b"PNGDATA"))
    assert st.exists("img/deadbeef_name.png")
    assert st.open("img/deadbeef_name.png").read() == b"PNGDATA"
    # 子目录键真的落到子目录(不再静默打平成 basename)。
    assert (tmp_path / "img" / "deadbeef_name.png").is_file()
    st.delete("img/deadbeef_name.png")
    assert not st.exists("img/deadbeef_name.png")


@pytest.mark.parametrize("bad", ["../escape.txt", "/abs.txt", "a/../../b", ""])
def test_localdisk_all_methods_reject_traversal(tmp_path, bad):
    st = LocalDiskStorage(tmp_path)
    with pytest.raises(StorageKeyError):
        st.save(bad, io.BytesIO(b"x"))
    with pytest.raises(StorageKeyError):
        st.open(bad)
    with pytest.raises(StorageKeyError):
        st.delete(bad)
    with pytest.raises(StorageKeyError):
        st.exists(bad)
