"""search_text 组装(I10):应用层写路径重算,拼所有语言 name + spec value + sku_code。

不含 description(P0 不做);喂 pg_trgm GIN。
"""
from __future__ import annotations


def build_search_text(name_i18n: dict | None, spec_items: list[dict], sku_code: str) -> str:
    tokens: list[str] = []
    for val in (name_i18n or {}).values():
        if val:
            tokens.append(val)
    for item in spec_items or []:
        value = item.get("value")
        if isinstance(value, dict):
            tokens.extend(v for v in value.values() if v)
        elif value is not None and value != "":
            tokens.append(str(value))
    if sku_code:
        tokens.append(sku_code)
    return " ".join(tokens)
