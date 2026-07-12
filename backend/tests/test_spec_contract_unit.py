import pytest

from app.core.exceptions import SpecContractError
from app.schemas.sku import validate_spec_items


def test_accepts_scalar_and_lang_map():
    items = validate_spec_items([
        {"key": "material", "value": {"zh": "不锈钢 304", "en": "SS304"}},
        {"key": "dn", "value": "DN50"},
        {"key": "pressure", "value": 1.6},
    ])
    assert len(items) == 3


def test_spec_item_has_no_unit_field():
    """spec §11 Part B:计量单位只住模板 category_spec_attributes.unit,spec_jsonb
    落库形状(SpecItem)不再承载 unit —— 传了也不会出现在解析结果里。"""
    items = validate_spec_items([{"key": "pressure", "value": 1.6}])
    assert not hasattr(items[0], "unit")


def test_rejects_duplicate_key():
    with pytest.raises(SpecContractError):
        validate_spec_items([{"key": "dn", "value": "1"}, {"key": "dn", "value": "2"}])


def test_rejects_lang_map_without_zh():
    with pytest.raises(SpecContractError):
        validate_spec_items([{"key": "m", "value": {"en": "SS304"}}])


def test_rejects_empty_string_in_lang_map():
    with pytest.raises(SpecContractError):
        validate_spec_items([{"key": "m", "value": {"zh": "钢", "en": ""}}])


def test_rejects_empty_key():
    with pytest.raises(SpecContractError):
        validate_spec_items([{"key": "", "value": "x"}])
