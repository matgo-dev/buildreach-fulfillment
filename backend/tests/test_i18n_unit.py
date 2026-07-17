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


def test_compose_spec_text_orders_by_template_compact_no_label():
    # 去标签、值+单位紧凑无空格、按 sort_order 排、` / ` 连接
    suggestions = {
        "range": {"unit": "", "sort_order": 10, "value_type": "string"},
        "division": {"unit": "g", "sort_order": 20, "value_type": "number"},
    }
    spec = [
        {"key": "division", "value": 0.5},
        {"key": "range", "value": "0.02–15kg"},
    ]
    # range(浅层)在前、division(深层)在后;division 数值 0.5 紧跟单位 g → 0.5g
    assert compose_spec_text(spec, suggestions, "zh") == "0.02–15kg / 0.5g"


def test_compose_spec_text_translates_enum_code_by_lang():
    # enum 存 code,须查 options 翻 label_i18n 再按语言取(修裸 code bug)
    suggestions = {
        "material": {
            "value_type": "enum", "unit": "", "sort_order": 10,
            "options": [{"code": "ss304", "label_i18n": {"zh": "304不锈钢", "en": "SS304"}}],
        }
    }
    spec = [{"key": "material", "value": "ss304"}]
    assert compose_spec_text(spec, suggestions, "zh") == "304不锈钢"
    assert compose_spec_text(spec, suggestions, "en") == "SS304"


def test_compose_spec_text_int_value_stays_compact():
    # number 标量原样 str,int 保持 15 不变 15.0;单位紧跟无空格
    suggestions = {"length": {"unit": "mm", "sort_order": 10, "value_type": "number"}}
    assert compose_spec_text([{"key": "length", "value": 15}], suggestions, "zh") == "15mm"


def test_compose_spec_text_empty_axis_is_empty():
    assert compose_spec_text([], {}, "zh") == ""


def test_compose_spec_text_unknown_enum_code_falls_back_to_code():
    # code 不在 options(理论上写路径已校验)→ 原样输出 code,不静默丢
    suggestions = {"material": {"value_type": "enum", "unit": "", "sort_order": 10, "options": []}}
    assert compose_spec_text([{"key": "material", "value": "unknown_x"}], suggestions, "zh") == "unknown_x"
