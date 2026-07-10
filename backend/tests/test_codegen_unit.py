from app.core.codegen import format_code
from app.services.numbering import NumberScope


def test_sku_code_format_is_neutral_prefixed_zero_padded():
    # 主数据:SKU 前缀 + 8 位零填充全局序号,不编码任何商品属性
    assert format_code(NumberScope.SKU, 42) == "SKU00000042"
    assert format_code(NumberScope.SKU, 123456789) == "SKU123456789"  # 超位自然增长


def test_customer_code_format():
    assert format_code(NumberScope.CUSTOMER, 42) == "C000042"


def test_quote_no_format_period_plus_running_seq():
    # 单据:Q + 年月(YYYYMM)+ 期内 4 位序号
    assert format_code(NumberScope.QUOTATION, 1, "202607") == "Q2026070001"
    assert format_code(NumberScope.QUOTATION, 42, "202607") == "Q2026070042"


def test_format_code_spu():
    assert format_code(NumberScope.SPU, 42) == "SPU00000042"


def test_format_code_matches_legacy_shapes():
    assert format_code(NumberScope.SKU, 42) == "SKU00000042"
    assert format_code(NumberScope.CUSTOMER, 42) == "C000042"
    assert format_code(NumberScope.QUOTATION, 1, "202607") == "Q2026070001"


def test_format_code_unknown_scope_raises():
    import pytest
    with pytest.raises(KeyError):
        format_code("NOPE", 1)
