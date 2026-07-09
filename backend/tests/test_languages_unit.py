from app.core.languages import SUPPORTED_QUOTE_LANGUAGES, resolve_quote_language


def test_supported_set_is_zh_en_sw():
    assert SUPPORTED_QUOTE_LANGUAGES == ("zh", "en", "sw")


def test_resolve_maps_known_bcp47():
    assert resolve_quote_language("zh-CN") == "zh"
    assert resolve_quote_language("sw-TZ") == "sw"


def test_resolve_unknown_bcp47_falls_back_to_en():
    assert resolve_quote_language("ar-SA") == "en"
    assert resolve_quote_language("en") == "en"


def test_resolve_none_or_empty_defaults_zh():
    # M1 内容纯中文:无客户偏好时报价默认 zh(设计 §3.6/§5)
    assert resolve_quote_language(None) == "zh"
    assert resolve_quote_language("") == "zh"
