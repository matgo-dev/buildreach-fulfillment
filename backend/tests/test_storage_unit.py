"""LocalDiskStorage 纯逻辑单测:roundtrip(save/exists/open/delete),无外部依赖。"""
from io import BytesIO


def test_local_disk_roundtrip(tmp_path):
    from app.services.storage import LocalDiskStorage

    s = LocalDiskStorage(tmp_path)
    s.save("a.txt", BytesIO(b"hello"))
    assert s.exists("a.txt")
    assert s.open("a.txt").read() == b"hello"
    s.delete("a.txt")
    assert not s.exists("a.txt")
