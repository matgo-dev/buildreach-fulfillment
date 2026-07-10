"""SPU schemas。"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.schemas.customer import _require_zh  # 复用 zh 必填/禁空串校验


class SpuCreateIn(BaseModel):
    category_code: str = Field(..., max_length=50)
    name_i18n: dict

    _v = field_validator("name_i18n")(_require_zh)


class SpuOut(BaseModel):
    id: int
    category_code: str
    name_i18n: dict
    status: str
