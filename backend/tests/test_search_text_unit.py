from app.core.search_text import build_search_text


def test_build_joins_all_langs_names_spec_values_and_code():
    name = {"zh": "不锈钢法兰球阀 DN50", "en": "Stainless Steel Flanged Ball Valve DN50"}
    spec = [
        {"key": "material", "value": {"zh": "不锈钢 304", "en": "SS304"}},
        {"key": "dn", "value": "DN50"},        # 中性标量
        {"key": "pressure", "value": "1.6"},
    ]
    got = build_search_text(name, spec, "SKUAB23CD45EF")
    for token in ["不锈钢法兰球阀 DN50", "Stainless Steel Flanged Ball Valve DN50",
                  "不锈钢 304", "SS304", "DN50", "1.6", "SKUAB23CD45EF"]:
        assert token in got


def test_build_skips_empty_and_none_and_handles_no_spec():
    got = build_search_text({"zh": "阀", "en": ""}, [], "SKUX")
    assert "阀" in got and "SKUX" in got
    assert got.count("  ") == 0  # 不留空 token 造成双空格
