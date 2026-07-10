import pytest

from app.core.exceptions import SpecContractError
from app.schemas.sku import validate_spec_items


def test_accepts_scalar_and_lang_map():
    items = validate_spec_items([
        {"key": "material", "value": {"zh": "不锈钢 304", "en": "SS304"}},
        {"key": "dn", "value": "DN50"},
        {"key": "pressure", "value": 1.6, "unit": "MPa"},
    ])
    assert len(items) == 3


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
