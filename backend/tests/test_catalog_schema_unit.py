import pytest
from decimal import Decimal
from pydantic import ValidationError

from app.schemas.common import validate_i18n
from app.schemas.sku import SkuCreateIn


def test_i18n_requires_zh_trimmed_nonempty():
    with pytest.raises(Exception):
        validate_i18n({"zh": "   "})
    assert validate_i18n({"zh": "钢管"}) == {"zh": "钢管"}


def test_i18n_rejects_unknown_lang_key():
    with pytest.raises(Exception):
        validate_i18n({"zh": "x", "fr": "y"})


def test_i18n_rejects_empty_value():
    with pytest.raises(Exception):
        validate_i18n({"zh": "x", "en": ""})


def test_reference_price_rejects_three_decimals():
    with pytest.raises(ValidationError):
        SkuCreateIn(spu_id=1, unit="piece", name_i18n={"zh": "x"},
                    reference_price=Decimal("1.234"), spec_items=[])


def test_reference_price_rejects_negative():
    with pytest.raises(ValidationError):
        SkuCreateIn(spu_id=1, unit="piece", name_i18n={"zh": "x"},
                    reference_price=Decimal("-1"), spec_items=[])
