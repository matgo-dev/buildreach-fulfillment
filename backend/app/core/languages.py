"""报价语言集合(单一源头)。

集合定死 zh/en/sw;客户直接三选一存(customers.quote_language),报价单/行继承。
VARCHAR + DB CHECK + 应用层校验,不用 DB enum。
"""
from __future__ import annotations

SUPPORTED_QUOTE_LANGUAGES: tuple[str, ...] = ("zh", "en", "sw")

# 客户未指定报价语言时的缺省(M1 内容纯中文)。
DEFAULT_QUOTE_LANGUAGE: str = "zh"


def is_supported_quote_language(lang: str) -> bool:
    return lang in SUPPORTED_QUOTE_LANGUAGES
