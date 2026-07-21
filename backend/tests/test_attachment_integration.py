"""附件增量:中转上传(三层类型校验 42101 / 超大 42102 / 孤儿配额 42103)+ 逐文件下载
scope(孤儿仅上传者、已挂报关走 shipment:read、软删不可下 42104)+ 删孤儿 + 报关关联/替换/
级联软删。RBAC:上传/删孤儿守 shipment:manage。

file bytes 用真实文件头(libmagic 按内容嗅探):PDF=%PDF、PNG=\x89PNG。
"""
import pytest

from app.core.config import settings
from app.services import attachment_service
from tests.outbound_helpers import make_loadable_shipment

pytestmark = pytest.mark.asyncio

_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
_PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x00IEND\xaeB`\x82")


async def _upload(client, headers, name, content, mime):
    return await client.post("/api/v1/attachments", headers=headers,
                             files={"file": (name, content, mime)})


async def _loaded(client, db_session, sales_headers, purchaser_headers, logistics_headers):
    d = await make_loadable_shipment(client, db_session, sales_headers, purchaser_headers,
                                     logistics_headers)
    ship = d["shipment"]
    ld = await client.post(f"/api/v1/shipments/{ship['id']}/load", headers=logistics_headers,
                           json={"expected_updated_at": ship["updated_at"]})
    assert ld.status_code == 200, ld.text
    return ship["id"]


# ---------- 上传:类型 / 大小 / 配额 ----------


async def test_upload_valid_pdf(client, logistics_headers):
    r = await _upload(client, logistics_headers, "报关单.pdf", _PDF, "application/pdf")
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["original_filename"] == "报关单.pdf"
    assert d["content_type"] == "application/pdf"
    assert d["download_url"] == f"/api/v1/attachments/{d['id']}/download"


async def test_upload_type_mismatch_42101(client, logistics_headers):
    """.pdf 扩展名但内容是纯文本(嗅探 text/plain 不入 pdf 族)→ 42101。"""
    r = await _upload(client, logistics_headers, "fake.pdf", b"just plain text", "application/pdf")
    assert r.status_code == 422 and r.json()["code"] == 42101, r.text


async def test_upload_ext_not_allowed_42101(client, logistics_headers):
    """白名单外扩展名(.exe)→ 42101。"""
    r = await _upload(client, logistics_headers, "x.exe", b"MZ...", "application/octet-stream")
    assert r.status_code == 422 and r.json()["code"] == 42101, r.text


async def test_upload_too_large_42102(client, logistics_headers, monkeypatch):
    """超大小上限 → 42102(monkeypatch 小上限,避免真传 50MB)。"""
    monkeypatch.setattr(settings, "ATTACHMENT_MAX_SIZE_BYTES", 10)
    r = await _upload(client, logistics_headers, "big.pdf", _PDF, "application/pdf")
    assert r.status_code == 413 and r.json()["code"] == 42102, r.text


async def test_orphan_quota_42103(client, logistics_headers, monkeypatch):
    """孤儿配额:超数量上限 → 42103(monkeypatch 上限=2)。"""
    monkeypatch.setattr(settings, "ATTACHMENT_ORPHAN_QUOTA_COUNT", 2)
    assert (await _upload(client, logistics_headers, "a.pdf", _PDF, "application/pdf")).status_code == 200
    assert (await _upload(client, logistics_headers, "b.pdf", _PDF, "application/pdf")).status_code == 200
    third = await _upload(client, logistics_headers, "c.pdf", _PDF, "application/pdf")
    assert third.status_code == 422 and third.json()["code"] == 42103, third.text


async def test_orphan_byte_quota_counts_incoming_42103(client, logistics_headers, monkeypatch):
    """字节配额按「已有 + 本次」判:存量未超但加上本次会超 → 42103(不再能末笔突破上限)。"""
    monkeypatch.setattr(settings, "ATTACHMENT_ORPHAN_QUOTA_BYTES", len(_PDF) + 5)
    assert (await _upload(client, logistics_headers, "a.pdf", _PDF, "application/pdf")).status_code == 200
    second = await _upload(client, logistics_headers, "b.pdf", _PDF, "application/pdf")
    assert second.status_code == 422 and second.json()["code"] == 42103, second.text


async def test_expired_orphan_reaped_on_upload(client, db_session, logistics_headers, monkeypatch):
    """过期孤儿惰性回收:占满配额的孤儿过期后,下次上传顺手软删回收 → 配额解锁,
    过期件下载 42104(不再出现「遗留孤儿永久锁死 42103」)。"""
    from datetime import timedelta as _td

    from sqlalchemy import update

    from app.db.base import _utcnow
    from app.db.models.attachment import Attachment

    monkeypatch.setattr(settings, "ATTACHMENT_ORPHAN_QUOTA_COUNT", 1)
    old = await _upload(client, logistics_headers, "old.pdf", _PDF, "application/pdf")
    old_id = old.json()["data"]["id"]
    # 配额已满(1/1)→ 再传被拦。
    blocked = await _upload(client, logistics_headers, "new.pdf", _PDF, "application/pdf")
    assert blocked.status_code == 422 and blocked.json()["code"] == 42103, blocked.text
    # 把存量孤儿拨到 TTL 之外。
    await db_session.execute(update(Attachment).where(Attachment.id == old_id).values(
        created_at=_utcnow() - _td(hours=settings.ATTACHMENT_ORPHAN_TTL_HOURS + 1)))
    await db_session.commit()
    # 过期后上传:先回收再查配额 → 通过;过期件被软删,下载 42104。
    ok = await _upload(client, logistics_headers, "new.pdf", _PDF, "application/pdf")
    assert ok.status_code == 200, ok.text
    gone = await client.get(f"/api/v1/attachments/{old_id}/download", headers=logistics_headers)
    assert gone.status_code == 404 and gone.json()["code"] == 42104, gone.text


# ---------- 下载 scope ----------


async def test_orphan_download_uploader_only(client, logistics_headers, sales_headers):
    """孤儿:上传者本人可下;他人(SALES)→ 42104(不暴露存在性)。"""
    up = await _upload(client, logistics_headers, "o.pdf", _PDF, "application/pdf")
    aid = up.json()["data"]["id"]
    ok = await client.get(f"/api/v1/attachments/{aid}/download", headers=logistics_headers)
    assert ok.status_code == 200 and ok.content == _PDF
    assert ok.headers["x-content-type-options"] == "nosniff"
    assert "attachment;" in ok.headers["content-disposition"]
    other = await client.get(f"/api/v1/attachments/{aid}/download", headers=sales_headers)
    assert other.status_code == 404 and other.json()["code"] == 42104, other.text


async def test_linked_download_by_shipment_read(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """已挂报关的附件:shipment:read(SALES)可下(报关单证非红线)。"""
    sid = await _loaded(client, db_session, sales_headers, purchaser_headers, logistics_headers)
    up = await _upload(client, logistics_headers, "d.pdf", _PDF, "application/pdf")
    aid = up.json()["data"]["id"]
    cr = await client.post(f"/api/v1/shipments/{sid}/customs-declarations",
                           headers=logistics_headers,
                           json={"declaration_no": "CN1", "declared_at": "2026-07-19",
                                 "attachment_ids": [aid]})
    assert cr.status_code == 200, cr.text
    atts = cr.json()["data"]["customs_declaration"]["attachments"]
    assert [a["id"] for a in atts] == [aid]
    # SALES(shipment:read)可下已挂附件。
    r = await client.get(f"/api/v1/attachments/{aid}/download", headers=sales_headers)
    assert r.status_code == 200 and r.content == _PDF


async def test_removed_attachment_not_downloadable_42104(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """PATCH 全量替换移出附件 → 软删 → 下载 42104(F19:移出的 URL 不得继续可达)。"""
    sid = await _loaded(client, db_session, sales_headers, purchaser_headers, logistics_headers)
    a1 = (await _upload(client, logistics_headers, "1.pdf", _PDF, "application/pdf")).json()["data"]["id"]
    a2 = (await _upload(client, logistics_headers, "2.pdf", _PDF, "application/pdf")).json()["data"]["id"]
    cr = await client.post(f"/api/v1/shipments/{sid}/customs-declarations",
                           headers=logistics_headers,
                           json={"declaration_no": "CN2", "declared_at": "2026-07-19",
                                 "attachment_ids": [a1, a2]})
    decl = cr.json()["data"]["customs_declaration"]
    # 替换为仅 a1 → a2 被移出软删。
    up = await client.patch(f"/api/v1/shipments/{sid}/customs-declarations/{decl['id']}",
                            headers=logistics_headers,
                            json={"attachment_ids": [a1], "expected_updated_at": decl["updated_at"]})
    assert up.status_code == 200, up.text
    assert [a["id"] for a in up.json()["data"]["customs_declaration"]["attachments"]] == [a1]
    gone = await client.get(f"/api/v1/attachments/{a2}/download", headers=logistics_headers)
    assert gone.status_code == 404 and gone.json()["code"] == 42104, gone.text
    assert (await client.get(f"/api/v1/attachments/{a1}/download",
                             headers=logistics_headers)).status_code == 200


async def test_cascade_soft_delete_attachments(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """软删报关 → 级联软删附件 → 附件不可下 42104。"""
    sid = await _loaded(client, db_session, sales_headers, purchaser_headers, logistics_headers)
    aid = (await _upload(client, logistics_headers, "c.pdf", _PDF, "application/pdf")).json()["data"]["id"]
    cr = await client.post(f"/api/v1/shipments/{sid}/customs-declarations",
                           headers=logistics_headers,
                           json={"declaration_no": "CN3", "declared_at": "2026-07-19",
                                 "attachment_ids": [aid]})
    decl_id = cr.json()["data"]["customs_declaration"]["id"]
    await client.delete(f"/api/v1/shipments/{sid}/customs-declarations/{decl_id}",
                        headers=logistics_headers)
    gone = await client.get(f"/api/v1/attachments/{aid}/download", headers=logistics_headers)
    assert gone.status_code == 404 and gone.json()["code"] == 42104, gone.text


# ---------- 删孤儿 + 数量上限 ----------


async def test_delete_orphan_then_unavailable(client, logistics_headers):
    """删孤儿(误传纠错)→ 之后下载 42104。"""
    aid = (await _upload(client, logistics_headers, "o.pdf", _PDF, "application/pdf")).json()["data"]["id"]
    dl = await client.delete(f"/api/v1/attachments/{aid}", headers=logistics_headers)
    assert dl.status_code == 200, dl.text
    gone = await client.get(f"/api/v1/attachments/{aid}/download", headers=logistics_headers)
    assert gone.status_code == 404 and gone.json()["code"] == 42104


async def test_delete_linked_orphan_endpoint_rejects(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """已挂报关的附件不能走删孤儿端点(仅未关联可删)→ 42104。"""
    sid = await _loaded(client, db_session, sales_headers, purchaser_headers, logistics_headers)
    aid = (await _upload(client, logistics_headers, "d.pdf", _PDF, "application/pdf")).json()["data"]["id"]
    await client.post(f"/api/v1/shipments/{sid}/customs-declarations", headers=logistics_headers,
                      json={"declaration_no": "CN4", "declared_at": "2026-07-19",
                            "attachment_ids": [aid]})
    r = await client.delete(f"/api/v1/attachments/{aid}", headers=logistics_headers)
    assert r.status_code == 404 and r.json()["code"] == 42104, r.text


async def test_attachment_count_limit_42105(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, monkeypatch):
    """单报关记录附件数超上限 → 42105(monkeypatch 上限=1)。"""
    monkeypatch.setattr(settings, "ATTACHMENT_MAX_PER_OWNER", 1)
    sid = await _loaded(client, db_session, sales_headers, purchaser_headers, logistics_headers)
    a1 = (await _upload(client, logistics_headers, "1.pdf", _PDF, "application/pdf")).json()["data"]["id"]
    a2 = (await _upload(client, logistics_headers, "2.pdf", _PDF, "application/pdf")).json()["data"]["id"]
    r = await client.post(f"/api/v1/shipments/{sid}/customs-declarations", headers=logistics_headers,
                          json={"declaration_no": "CN5", "declared_at": "2026-07-19",
                                "attachment_ids": [a1, a2]})
    assert r.status_code == 422 and r.json()["code"] == 42105, r.text


# ---------- Content-Disposition(文件名安全编码)----------


async def test_content_disposition_strips_quotes_and_crlf():
    """quoted-string 恒合法:双引号/CRLF/控制字符全清洗;中文名走 filename*(RFC 5987)。"""
    cd = attachment_service.content_disposition('a"b\r\nc.pdf')
    assert "\r" not in cd and "\n" not in cd
    # 双引号被清洗:quoted-string 内不残留 `"`(逐字符替换 `"`/`\r`/`\n` → `_`)。
    assert cd.startswith('attachment; filename="a_b__c.pdf"')
    cd_cn = attachment_service.content_disposition("报关单.pdf")
    assert "filename*=UTF-8''%E6%8A%A5%E5%85%B3%E5%8D%95.pdf" in cd_cn


# ---------- RBAC ----------


async def test_rbac_upload_requires_manage(client, sales_headers, superadmin_headers):
    """上传守 shipment:manage:SALES(只读)、ADMIN(系统域)均 403。"""
    for h in (sales_headers, superadmin_headers):
        r = await _upload(client, h, "x.pdf", _PDF, "application/pdf")
        assert r.status_code == 403, r.text
