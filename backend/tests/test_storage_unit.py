"""Storage 纯逻辑单测:roundtrip + build_url/create_upload 形状,无外部依赖(mock/不落盘)。"""
from io import BytesIO
from unittest.mock import MagicMock


def test_local_disk_roundtrip(tmp_path):
    from app.services.storage import LocalDiskStorage

    s = LocalDiskStorage(tmp_path)
    s.save("a.txt", BytesIO(b"hello"))
    assert s.exists("a.txt")
    assert s.open("a.txt").read() == b"hello"
    s.delete("a.txt")
    assert not s.exists("a.txt")


def test_local_disk_build_url_ignores_size(tmp_path):
    from app.services.storage import LocalDiskStorage

    s = LocalDiskStorage(tmp_path)
    assert s.build_url("img/a.jpg") == "/api/v1/media/img/a.jpg"
    # size 传了也忽略(本地零图像处理,浏览器降采样)
    assert s.build_url("img/a.jpg", size=80) == "/api/v1/media/img/a.jpg"


def test_local_disk_create_upload_points_back_to_upload_endpoint(tmp_path):
    from app.services.storage import LocalDiskStorage

    s = LocalDiskStorage(tmp_path)
    result = s.create_upload("img/a.jpg", "image/jpeg")
    assert result == {
        "key": "img/a.jpg",
        "upload_url": "/api/v1/uploads/img/a.jpg",
        "method": "PUT",
    }


def _s3_storage(**overrides):
    from app.services.storage import S3Storage

    kwargs = dict(
        endpoint_url="", region="cn-hangzhou", access_key="ak", secret_key="sk",
        bucket="bucket", public_base_url="https://cdn.example.com")
    kwargs.update(overrides)
    return S3Storage(**kwargs)


def test_s3_build_url_no_size():
    s = _s3_storage()
    assert s.build_url("img/a.jpg") == "/api/v1/media/img/a.jpg"


def test_s3_build_url_ignores_size_returns_original():
    # 标准 S3 兼容存储(MinIO / OVH Object Storage)无 URL 传参改尺寸能力,size 被忽略。
    s = _s3_storage()
    assert s.build_url("img/a.jpg", size=80) == "/api/v1/media/img/a.jpg"


def test_s3_create_upload_returns_presigned_put_url():
    s = _s3_storage()
    s._client = MagicMock()
    s._client.generate_presigned_url.return_value = "https://bucket.oss.example.com/img/a.jpg?sig=xxx"

    result = s.create_upload("img/a.jpg", "image/jpeg")

    assert result == {
        "key": "img/a.jpg",
        "upload_url": "https://bucket.oss.example.com/img/a.jpg?sig=xxx",
        "method": "PUT",
    }
    s._client.generate_presigned_url.assert_called_once_with(
        "put_object",
        Params={"Bucket": "bucket", "Key": "img/a.jpg", "ContentType": "image/jpeg"},
        ExpiresIn=300,
    )
