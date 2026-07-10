"""SKU schemas + spec_jsonb Pydantic 契约(防漂移,来自 i18n 方案 §4.2b)。"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, ValidationError, condecimal, field_validator

from app.core.exceptions import SpecContractError
from app.schemas.common import validate_i18n


class SpecItem(BaseModel):
    key: str
    value: str | float | int | dict[str, str]
    unit: str | None = None

    @field_validator("key")
    @classmethod
    def _key_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("key 非空")
        return v

    @field_validator("value")
    @classmethod
    def _value_lang_map_zh(cls, v):
        if isinstance(v, dict):
            if not v.get("zh"):
                raise ValueError("语言映射 zh 必填")
            if any(val in ("", None) for val in v.values()):
                raise ValueError("禁止空串/空值")
        return v


def validate_spec_items(items: list[dict]) -> list[SpecItem]:
    """形状 + 唯一性校验(不查模板)。失败一律抛 SpecContractError。"""
    try:
        parsed = [SpecItem.model_validate(it) for it in items]
    except ValidationError as e:
        raise SpecContractError(str(e.errors()))
    keys = [p.key for p in parsed]
    if len(keys) != len(set(keys)):
        raise SpecContractError("同一 SKU 内 key 必须唯一")
    return parsed


class SkuSpecItemIn(BaseModel):
    # key 可缺省:新属性(带 label_i18n)由后端生成稳定键,不接受调用方直接指定
    # 中文/任意原文当 key —— 身份≠展示铁律(_resolve_spec 强制)。
    key: str | None = None
    value: str | float | int | dict[str, str]
    unit: str | None = None
    label_i18n: dict | None = None  # 新属性时带(zh 必填),回写模板用


class SkuCreateIn(BaseModel):
    spu_id: int
    unit: str = Field(..., max_length=20)
    reference_price: condecimal(ge=0, max_digits=18, decimal_places=2) | None = None
    name_i18n: dict
    spec_items: list[SkuSpecItemIn] = []
    image: str | None = Field(default=None, max_length=255)

    _v = field_validator("name_i18n")(validate_i18n)


class SkuUpdateIn(BaseModel):
    name_i18n: dict | None = None
    unit: str | None = None
    reference_price: condecimal(ge=0, max_digits=18, decimal_places=2) | None = None
    spec_items: list[SkuSpecItemIn] | None = None
    image: str | None = Field(default=None, max_length=255)

    @field_validator("name_i18n")
    @classmethod
    def _v_name(cls, v):
        # 部分更新:仅当提供 name_i18n 时才校验 zh 必填/禁空串(与 create 一致)
        return validate_i18n(v) if v is not None else v


class SkuOut(BaseModel):
    id: int
    spu_id: int
    sku_code: str
    unit: str
    reference_price: Decimal | None
    spec_jsonb: list
    name_i18n: dict
    search_text: str
    status: str
    image: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


def sku_out(sku, *, include_cost: bool, spu_main_image: str | None = None) -> dict:
    """序列化 SKU;include_cost=False 时脱敏 reference_price(置 None)。

    spu_main_image 给定时附加同名字段,供前端跨 SPU 场景(搜索行/单取)做
    `sku.image ?? spu_main_image` 回退——本模型不存 SPU 全量信息,只搭一个字段。
    """
    data = SkuOut.model_validate(sku).model_dump()
    if not include_cost:
        data["reference_price"] = None
    if spu_main_image is not None:
        data["spu_main_image"] = spu_main_image
    return data
