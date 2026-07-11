"""SPU schemas。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import validate_i18n


def _require_nonempty_image(v: str) -> str:
    """main_image 必填(trim 后非空)——商品图非红线但主图不留空(展示回退基石)。"""
    if not v or not v.strip():
        raise ValueError("main_image 必填且禁空串")
    return v.strip()


class SpuCreateIn(BaseModel):
    category_code: str = Field(..., max_length=50)
    name_i18n: dict
    main_image: str = Field(..., max_length=255)
    images: list[str] = []

    _v = field_validator("name_i18n")(validate_i18n)
    _v_img = field_validator("main_image")(_require_nonempty_image)


class SpuOut(BaseModel):
    id: int
    spu_code: str
    category_code: str
    name_i18n: dict
    status: str
    main_image: str
    images: list
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SpuUpdateIn(BaseModel):
    name_i18n: dict | None = None
    category_code: str | None = Field(default=None, max_length=50)
    main_image: str | None = Field(default=None, max_length=255)
    images: list[str] | None = None

    @field_validator("name_i18n")
    @classmethod
    def _v_name(cls, v):
        return validate_i18n(v) if v is not None else v

    @field_validator("main_image")
    @classmethod
    def _v_main_image(cls, v):
        return _require_nonempty_image(v) if v is not None else v
