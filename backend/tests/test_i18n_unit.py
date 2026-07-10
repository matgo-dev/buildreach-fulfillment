from app.core.i18n import display, compose_spec_text


def test_display_hits_target_lang():
    assert display({"zh": "阀门", "en": "Valve"}, "en") == "Valve"


def test_display_fallback_chain_target_en_zh():
    # 目标 sw 缺 → en → zh
    assert display({"zh": "阀门", "en": "Valve"}, "sw") == "Valve"
    assert display({"zh": "阀门"}, "sw") == "阀门"


def test_display_missing_treats_empty_and_null_and_absent_alike():
    assert display({"zh": "阀门", "en": ""}, "en") == "阀门"      # 空串按 missing
    assert display({"zh": "阀门", "en": None}, "en") == "阀门"     # null 按 missing
    assert display(None, "zh") == ""
    assert display({}, "zh") == ""


def test_compose_spec_text_orders_by_template_and_formats():
    suggestions = {
        "material": {"label_i18n": {"zh": "材质"}, "unit": "", "sort_order": 10},
        "pressure": {"label_i18n": {"zh": "压力等级"}, "unit": "MPa", "sort_order": 30},
        "dn": {"label_i18n": {"zh": "公称通径"}, "unit": "", "sort_order": 20},
    }
    spec = [
        {"key": "pressure", "value": "1.6"},
        {"key": "material", "value": {"zh": "不锈钢 304"}},
        {"key": "dn", "value": "DN50"},
    ]
    got = compose_spec_text(spec, suggestions, "zh")
    assert got == "材质: 不锈钢 304, 公称通径: DN50, 压力等级: 1.6 MPa"


def test_compose_spec_text_uses_template_unit_and_value_fallback():
    suggestions = {"dn": {"label_i18n": {"zh": "通径", "en": "DN"}, "unit": "mm", "sort_order": 10}}
    spec = [{"key": "dn", "value": {"zh": "五十"}}]  # Part B:SKU 值不带 unit
    # en 报价:label 取 en;value 缺 en → 回落 zh;unit 取模板 mm(计量单位只住模板)
    assert compose_spec_text(spec, suggestions, "en") == "DN: 五十 mm"


def test_compose_spec_text_unknown_key_uses_key_as_label():
    # key 不在模板(理论上被 service 拦截,组合器需鲁棒)
    assert compose_spec_text([{"key": "x", "value": "1"}], {}, "zh") == "x: 1"
