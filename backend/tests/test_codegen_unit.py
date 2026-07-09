from app.core.codegen import format_customer_code, format_quote_no, format_sku_code


def test_sku_code_format_is_neutral_prefixed_zero_padded():
    # 主数据:SKU 前缀 + 8 位零填充全局序号,不编码任何商品属性
    assert format_sku_code(42) == "SKU00000042"
    assert format_sku_code(123456789) == "SKU123456789"  # 超位自然增长


def test_customer_code_format():
    assert format_customer_code(42) == "C000042"


def test_quote_no_format_period_plus_running_seq():
    # 单据:Q + 年月(YYYYMM)+ 期内 4 位序号
    assert format_quote_no("202607", 1) == "Q2026070001"
    assert format_quote_no("202607", 42) == "Q2026070042"
