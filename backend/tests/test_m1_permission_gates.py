import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/v1/customers", {"name_i18n": {"zh": "X"}}),
    ("post", "/api/v1/spus", {"category_code": "10", "name_i18n": {"zh": "X"}}),
    ("post", "/api/v1/skus", {"spu_id": 1, "unit": "PCS", "name_i18n": {"zh": "X"}, "spec_items": []}),
    ("post", "/api/v1/quotations", {"customer_id": 1, "currency": "USD"}),
    ("get", "/api/v1/skus?q=x", None),
])
async def test_endpoints_require_auth(client, method, path, body):
    # 无 token → require_permission 依赖先于业务/校验触发 401
    if body is not None:
        r = await getattr(client, method)(path, json=body)
    else:
        r = await getattr(client, method)(path)
    assert r.status_code == 401
