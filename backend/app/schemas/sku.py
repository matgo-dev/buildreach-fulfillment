"""SKU schemas + spec_jsonb Pydantic 契约(防漂移,来自 i18n 方案 §4.2b)。"""
from __future__ import annotations

from pydantic import BaseModel, ValidationError, field_validator

from app.core.exceptions import SpecContractError


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
            if any(val == "" for val in v.values()):
                raise ValueError("禁止空串")
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
