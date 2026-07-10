import pytest


@pytest.mark.asyncio
async def test_categories_tree_requires_read(client):
    assert (await client.get("/api/v1/categories/tree")).status_code == 401


@pytest.mark.asyncio
async def test_categories_tree_ok(client, superadmin_headers):
    r = await client.get("/api/v1/categories/tree", headers=superadmin_headers)
    assert r.status_code == 200
    assert isinstance(r.json()["data"]["items"], list)


@pytest.mark.asyncio
async def test_spec_suggestions_ok(client, superadmin_headers):
    r = await client.get("/api/v1/categories/10/spec-suggestions", headers=superadmin_headers)
    assert r.status_code in (200, 404)  # 该分类无模板则空/404,均可
