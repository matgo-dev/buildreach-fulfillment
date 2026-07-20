import pytest
from sqlalchemy import select

from app.db.models.category import Category


async def _seed_category(db_session, code="10"):
    if not (await db_session.execute(
            select(Category).where(Category.code == code))).scalar_one_or_none():
        db_session.add(Category(code=code, parent_code=None, name_i18n={"zh": "阀门"},
                                level=1, is_leaf=True, sort_order=0))
        await db_session.commit()


@pytest.mark.asyncio
async def test_readonly_can_read_but_cannot_manage(client, product_readonly_headers, db_session):
    await _seed_category(db_session)
    # 仅 product:read 无 product:manage → 建 SPU 应 403
    r = await client.post("/api/v1/spus", headers=product_readonly_headers,
                          json={"category_code": "10", "name_i18n": {"zh": "X"},
                               "images": [{"image_key": "img/test.jpg", "image_type": "MAIN", "sort_order": 0}]})
    assert r.status_code == 403
    # 有 product:read → 搜 SKU 应 200
    r2 = await client.get("/api/v1/skus?q=x", headers=product_readonly_headers)
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_catalog_operator_can_manage(client, product_operator_headers, db_session):
    await _seed_category(db_session)
    r = await client.post("/api/v1/spus", headers=product_operator_headers,
                          json={"category_code": "10", "name_i18n": {"zh": "钢管"},
                               "images": [{"image_key": "img/test.jpg", "image_type": "MAIN", "sort_order": 0}]})
    assert r.status_code in (200, 201), r.text
