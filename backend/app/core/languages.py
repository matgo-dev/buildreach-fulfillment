"""报价语言集合 + 客户偏好(BCP47)→ 报价语言映射(I8/I12)。

集合定死 zh/en/sw;VARCHAR + 应用层校验,不用 DB enum。
"""
from __future__ import annotations

SUPPORTED_QUOTE_LANGUAGES: tuple[str, ...] = ("zh", "en", "sw")


def resolve_quote_language(preferred: str | None) -> str:
    """客户偏好 BCP47 → 报价语言。

    - None/空:M1 内容纯中文 → 默认 zh;
    - zh-*/sw-* → zh/sw;其余已知 BCP47 → en 回落。
    """
    if not preferred:
        return "zh"
    if preferred.startswith("zh"):
        return "zh"
    if preferred.startswith("sw"):
        return "sw"
    return "en"


def is_supported_quote_language(lang: str) -> bool:
    return lang in SUPPORTED_QUOTE_LANGUAGES
