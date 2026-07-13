"""SPU schemas。图片规范化到 product_images:写接口携带图集 refs,后端按 key 对账。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import validate_i18n


class ImageRefIn(BaseModel):
    """SPU 图集项:封面 MAIN(恰 1)/ 轮播 GALLERY / 详情 DETAIL。"""
    image_key: str = Field(..., min_length=1, max_length=255)
    image_type: Literal["MAIN", "GALLERY", "DETAIL"] = "GALLERY"
    sort_order: int = 0


def validate_spu_image_refs(images: list[ImageRefIn]) -> list[ImageRefIn]:
    """校验:key 唯一;恰 1 MAIN(封面必备且唯一);主图组(MAIN+GALLERY)≤6;详情(DETAIL)≤12。"""
    keys = [i.image_key for i in images]
    if len(keys) != len(set(keys)):
        raise ValueError("图片 key 不能重复")
    main = sum(1 for i in images if i.image_type == "MAIN")
    if main != 1:
        raise ValueError("必须且只能有一张主图(封面)")
    if sum(1 for i in images if i.image_type in ("MAIN", "GALLERY")) > 6:
        raise ValueError("主图组(主图 + 轮播)最多 6 张")
    if sum(1 for i in images if i.image_type == "DETAIL") > 12:
        raise ValueError("详情图最多 12 张")
    return images


class SpuCreateIn(BaseModel):
    category_code: str = Field(..., max_length=50)
    name_i18n: dict
    brand: str | None = Field(default=None, max_length=100)
    description: str | None = None
    hs_code: str | None = Field(default=None, max_length=20)
    images: list[ImageRefIn]

    _v = field_validator("name_i18n")(validate_i18n)
    _v_img = field_validator("images")(validate_spu_image_refs)


class SpuOut(BaseModel):
    id: int
    spu_code: str
    category_code: str
    name_i18n: dict
    brand: str | None
    description: str | None
    hs_code: str | None
    status: str
    created_by: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SpuUpdateIn(BaseModel):
    name_i18n: dict | None = None
    category_code: str | None = Field(default=None, max_length=50)
    brand: str | None = Field(default=None, max_length=100)
    description: str | None = None
    hs_code: str | None = Field(default=None, max_length=20)
    images: list[ImageRefIn] | None = None

    @field_validator("name_i18n")
    @classmethod
    def _v_name(cls, v):
        return validate_i18n(v) if v is not None else v

    @field_validator("images")
    @classmethod
    def _v_images(cls, v):
        return validate_spu_image_refs(v) if v is not None else v
