"""多语言读取唯一入口 + spec_text 组合(I13 关键:把"以后加语言"降成纯数据)。"""
from __future__ import annotations


def display(field_i18n: dict | None, lang: str, fallback: str = "zh") -> str:
    """按 fallback 链 目标→en→fallback(默认 zh)取第一个非空值。

    null / "" / 缺 key 一律按 missing(I11)。
    """
    if not field_i18n:
        return ""
    for code in (lang, "en", fallback):
        val = field_i18n.get(code)
        if val:  # 空串 / None 都为 falsy → 跳过
            return val
    return ""


def compose_spec_text(
    spec_items: list[dict],
    suggestions_by_key: dict[str, dict],
    lang: str,
    fallback: str = "zh",
) -> str:
    """拼 SKU 变体轴规格短串(单据行快照的单一源头):值+单位紧凑无空格,` / ` 连接。

    只吃 SKU.spec_jsonb(变体轴)——产品级属性不进规格串(调用方 _compose_snapshot 只
    传 sku 轴)。运营在单据上区分变体只需值本身(`0.02–15kg / 0.5g`),标签冗余;标签仍在
    详情 spec_display 里可查。规则:

    - 去标签,值紧跟单位无空格(unit 只住模板,值本身不带单位)。
    - enum 标量存的是 option code,查模板 options 翻 label_i18n 再按 lang 取(修早先直接
      str(code) 露裸码的 bug);查不到该 code 就原样输出(鲁棒兜底,理论上写路径已校验)。
    - number/string 标量原样 str(不强转 float,int 保持 `15` 不变 `15.0`)。
    - 按模板 sort_order 排(get_suggestions 已重排成全局单调 rank);空轴 → 空串。
    """
    def _order(item: dict) -> int:
        return suggestions_by_key.get(item["key"], {}).get("sort_order", 9999)

    parts: list[str] = []
    for item in sorted(spec_items, key=_order):
        tmpl = suggestions_by_key.get(item["key"], {})
        value = item["value"]
        if isinstance(value, dict):
            value_str = display(value, lang, fallback)
        elif tmpl.get("value_type") == "enum":
            value_str = _enum_label(tmpl, value, lang, fallback)
        else:
            value_str = str(value)
        if not value_str:
            continue
        unit = tmpl.get("unit") or ""  # 计量单位只住模板(Part B 归位:SKU 值不带 unit)
        parts.append(f"{value_str}{unit}")
    return " / ".join(parts)


def _enum_label(tmpl: dict, code, lang: str, fallback: str) -> str:
    """enum 值域:把选中的 option code 翻成其 label_i18n 再按语言取;查不到原样输出 code。"""
    for opt in (tmpl.get("options") or []):
        if opt.get("code") == code:
            return display(opt.get("label_i18n"), lang, fallback)
    return str(code)
