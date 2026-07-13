"""search_text 组装(I10):应用层写路径重算,拼所有语言 name + spec value + sku_code。

不含 description(P0 不做);喂 pg_trgm GIN。

规格来源 = SPU 产品级 ∪ SKU 变体轴的并集(拆分后产品级属性住 SPU,搜索须并集,
见 sku_service._sku_search_text)。enum 值存的是 code,若给了模板则把 code 解析成各语言
label 也塞进索引(搜 `碳钢`/`304` 命中),同时保留 code;string/number 原样。
"""
from __future__ import annotations


def build_search_text(
    name_i18n: dict | None,
    spec_items: list[dict],
    sku_code: str,
    suggestions_by_key: dict[str, dict] | None = None,
) -> str:
    tokens: list[str] = []
    for val in (name_i18n or {}).values():
        if val:
            tokens.append(val)
    for item in spec_items or []:
        value = item.get("value")
        tmpl = (suggestions_by_key or {}).get(item.get("key"))
        # enum:把选中 code 对应的 option label(各语言)也入索引,搜中文/英文标签都能命中。
        if tmpl and tmpl.get("value_type") == "enum":
            for opt in (tmpl.get("options") or []):
                if opt.get("code") == value:
                    tokens.extend(v for v in (opt.get("label_i18n") or {}).values() if v)
                    break
        if isinstance(value, dict):
            tokens.extend(v for v in value.values() if v)
        elif value is not None and value != "":
            tokens.append(str(value))  # code / 标量原样保留(label 或 code 都可搜)
    if sku_code:
        tokens.append(sku_code)
    return " ".join(tokens)


def build_sku_search_text(
    *, spu_name_i18n, spu_brand, spu_spec, sku_name_i18n, sku_spec, sku_code,
    suggestions_by_key,
) -> str:
    """SKU 维度 search_text(单一源头):SPU 名+品牌+产品级规格 ∪ SKU 名+轴规格 + code。

    denormalize SPU 上下文进 SKU:搜"工字钢"(SPU 名)或"碳钢"(产品级属性)都能命中变体
    (报价等操作是 SKU 级)。→ SPU 名/品牌/规格变更须级联重算子 SKU(见 spu_service)。
    """
    tokens: dict = {}
    for k, v in (spu_name_i18n or {}).items():
        tokens[f"spu_{k}"] = v
    for k, v in (sku_name_i18n or {}).items():
        tokens[f"sku_{k}"] = v
    if spu_brand:
        tokens["brand"] = spu_brand
    merged_spec = list(spu_spec or []) + list(sku_spec or [])
    return build_search_text(tokens, merged_spec, sku_code, suggestions_by_key)


def build_spu_search_text(*, name_i18n, brand, spec, spu_code, suggestions_by_key) -> str:
    """SPU 维度 search_text:名+品牌+产品级规格(找商品)。变更只影响自身(无级联子)。"""
    tokens = dict(name_i18n or {})
    if brand:
        tokens["_brand"] = brand
    return build_search_text(tokens, spec, spu_code, suggestions_by_key)
