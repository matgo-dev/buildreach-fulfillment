"""SPU schemas。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import validate_i18n


class SpuCreateIn(BaseModel):
    category_code: str = Field(..., max_length=50)
    name_i18n: dict

    _v = field_validator("name_i18n")(validate_i18n)


class SpuOut(BaseModel):
    id: int
    spu_code: str
    category_code: str
    name_i18n: dict
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SpuUpdateIn(BaseModel):
    name_i18n: dict | None = None
    category_code: str | None = Field(default=None, max_length=50)

    @field_validator("name_i18n")
    @classmethod
    def _v_name(cls, v):
        return validate_i18n(v) if v is not None else v
