from app.core.languages import (
    DEFAULT_QUOTE_LANGUAGE,
    SUPPORTED_QUOTE_LANGUAGES,
    is_supported_quote_language,
)


def test_supported_set_is_zh_en_sw():
    assert SUPPORTED_QUOTE_LANGUAGES == ("zh", "en", "sw")


def test_default_is_zh():
    # M1 内容纯中文:客户未指定报价语言时建单默认 zh
    assert DEFAULT_QUOTE_LANGUAGE == "zh"


def test_is_supported():
    assert is_supported_quote_language("zh")
    assert is_supported_quote_language("sw")
    assert not is_supported_quote_language("sw-TZ")   # 只认三选一,不再吃 BCP47 细码
    assert not is_supported_quote_language("ar")
