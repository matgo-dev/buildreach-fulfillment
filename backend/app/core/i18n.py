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
    """按模板 sort_order 拼 `label[lang]: value[lang] (+unit)`,逗号连接。

    - label 取模板 label_i18n;value 标量直接用、词汇型过 display;
    - unit 取 SKU 级覆盖 > 模板默认;value 缺语言走 display 的 fallback 链。
    """
    def _order(item: dict) -> int:
        return suggestions_by_key.get(item["key"], {}).get("sort_order", 9999)

    parts: list[str] = []
    for item in sorted(spec_items, key=_order):
        tmpl = suggestions_by_key.get(item["key"], {})
        label = display(tmpl.get("label_i18n"), lang, fallback) or item["key"]
        value = item["value"]
        value_str = display(value, lang, fallback) if isinstance(value, dict) else str(value)
        unit = tmpl.get("unit") or ""  # 计量单位只住模板(Part B 归位:SKU 值不带 unit)
        seg = f"{label}: {value_str}" + (f" {unit}" if unit else "")
        parts.append(seg)
    return ", ".join(parts)
