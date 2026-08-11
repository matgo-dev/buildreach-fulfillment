import json

import pytest

from app.core.exceptions import BusinessError
from app.main import biz_exc_handler


@pytest.mark.asyncio
async def test_business_error_envelope_uses_biz_code_only():
    """错误响应只保留数字业务码,不再返回 message_key / message_params 双轨字段。"""
    response = await biz_exc_handler(
        None,  # type: ignore[arg-type]  handler 当前不读取 request
        BusinessError(http_status=409, biz_code=41401, message="Quotation is not a draft"),
    )
    body = json.loads(response.body)

    assert response.status_code == 409
    assert body == {
        "code": 41401,
        "message": "Quotation is not a draft",
        "data": None,
        "trace_id": "-",
    }
    assert "message_key" not in body
    assert "message_params" not in body
