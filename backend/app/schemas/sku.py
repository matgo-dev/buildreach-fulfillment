"""SKU schemas + spec_jsonb Pydantic 契约(防漂移,来自 i18n 方案 §4.2b)。"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, condecimal, field_validator

from app.core.exceptions import SpecContractError
from app.schemas.common import validate_i18n


class SpecItem(BaseModel):
    """spec_jsonb 落库形状(spec §11 Part B:计量单位归位,只住模板,永不落这里)。"""
    key: str
    value: str | float | int | dict[str, str]

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
    # enum 新增选项分支(带 label_i18n 且 code 不在模板 options 内)时可缺省/为 None——
    # 最终落库值由后端生成的选项 code 覆盖,不接受调用方越过校验直接指定 code。
    value: str | float | int | dict[str, str] | None = None
    # 仅在"新增属性"分支生效:落进该新属性模板行的计量单位(如新增"长度"顺手给
    # unit=mm)。对已存在的 key 一律忽略——计量单位以模板 category_spec_attributes.unit
    # 为准,不接受某个 SKU 单独覆盖(spec §11 Part B:单位归位,spec_jsonb 永不存 unit)。
    unit: str | None = None
    # 新属性时带(zh 必填),回写模板用;enum 已知属性时带 = 请求新增该属性一个新选项
    # (value 的 code 不在模板 options 内 + 带此字段 → inline 新增选项,label_i18n 即
    # 新选项展示名;code 不在 options 又不带此字段 → 仍 SpecContractError,不静默)
    label_i18n: dict | None = None


class SkuImageRefIn(BaseModel):
    """SKU 级图集项(该 SKU 专属图,无 MAIN/DETAIL 语义,后端一律记 GALLERY)。"""
    image_key: str = Field(..., min_length=1, max_length=255)
    sort_order: int = 0


def validate_sku_image_refs(images: list[SkuImageRefIn]) -> list[SkuImageRefIn]:
    keys = [i.image_key for i in images]
    if len(keys) != len(set(keys)):
        raise ValueError("图片 key 不能重复")
    if len(images) > 6:
        raise ValueError("SKU 图最多 6 张")
    return images


class SkuCreateIn(BaseModel):
    spu_id: int
    unit: str = Field(..., max_length=20)
    reference_price: condecimal(ge=0, max_digits=18, decimal_places=2) | None = None
    weight_kg: condecimal(ge=0, max_digits=12, decimal_places=3) | None = None
    length_cm: condecimal(ge=0, max_digits=10, decimal_places=2) | None = None
    width_cm: condecimal(ge=0, max_digits=10, decimal_places=2) | None = None
    height_cm: condecimal(ge=0, max_digits=10, decimal_places=2) | None = None
    name_i18n: dict
    spec_items: list[SkuSpecItemIn] = []
    images: list[SkuImageRefIn] = []

    _v = field_validator("name_i18n")(validate_i18n)
    _v_img = field_validator("images")(validate_sku_image_refs)


class SkuUpdateIn(BaseModel):
    name_i18n: dict | None = None
    unit: str | None = None
    reference_price: condecimal(ge=0, max_digits=18, decimal_places=2) | None = None
    weight_kg: condecimal(ge=0, max_digits=12, decimal_places=3) | None = None
    length_cm: condecimal(ge=0, max_digits=10, decimal_places=2) | None = None
    width_cm: condecimal(ge=0, max_digits=10, decimal_places=2) | None = None
    height_cm: condecimal(ge=0, max_digits=10, decimal_places=2) | None = None
    spec_items: list[SkuSpecItemIn] | None = None
    images: list[SkuImageRefIn] | None = None

    @field_validator("name_i18n")
    @classmethod
    def _v_name(cls, v):
        # 部分更新:仅当提供 name_i18n 时才校验 zh 必填/禁空串(与 create 一致)
        return validate_i18n(v) if v is not None else v

    @field_validator("images")
    @classmethod
    def _v_images(cls, v):
        return validate_sku_image_refs(v) if v is not None else v


class SkuOut(BaseModel):
    id: int
    spu_id: int
    sku_code: str
    unit: str
    reference_price: Decimal | None
    weight_kg: Decimal | None
    length_cm: Decimal | None
    width_cm: Decimal | None
    height_cm: Decimal | None
    spec_jsonb: list
    name_i18n: dict
    search_text: str
    status: str
    created_by: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


def sku_out(sku, *, include_cost: bool, spu_main_image: str | None = None,
            images: list | None = None) -> dict:
    """序列化 SKU;include_cost=False 时脱敏 reference_price(置 None)。

    images 给定时附加 SKU 级图集(product_images,sku_id 非空行)。
    spu_main_image 给定时附加同名字段,供前端跨 SPU 场景(搜索行)做
    `SKU 首图 ?? spu_main_image` 回退——本模型不存 SPU 信息,只搭一个字段。
    """
    data = SkuOut.model_validate(sku).model_dump()
    if not include_cost:
        data["reference_price"] = None
    if images is not None:
        data["images"] = images
    if spu_main_image is not None:
        data["spu_main_image"] = spu_main_image
    return data
