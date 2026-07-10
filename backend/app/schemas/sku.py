"""SKU schemas + spec_jsonb Pydantic 契约(防漂移,来自 i18n 方案 §4.2b)。"""
from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.exceptions import SpecContractError
from app.schemas.customer import _require_zh


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
    key: str
    value: str | float | int | dict[str, str]
    unit: str | None = None
    label_i18n: dict | None = None  # 手输新 key 时带,回写模板用


class SkuCreateIn(BaseModel):
    spu_id: int
    unit: str = Field(..., max_length=20)
    reference_price: float | None = None
    name_i18n: dict
    spec_items: list[SkuSpecItemIn] = []

    _v = field_validator("name_i18n")(_require_zh)


class SkuUpdateIn(BaseModel):
    name_i18n: dict | None = None
    unit: str | None = None
    reference_price: float | None = None
    spec_items: list[SkuSpecItemIn] | None = None

    @field_validator("name_i18n")
    @classmethod
    def _v_name(cls, v):
        # 部分更新:仅当提供 name_i18n 时才校验 zh 必填/禁空串(与 create 一致)
        return _require_zh(v) if v is not None else v


class SkuOut(BaseModel):
    id: int
    spu_id: int
    sku_code: str
    unit: str
    reference_price: float | None
    spec_jsonb: list
    name_i18n: dict
    search_text: str
    status: str
