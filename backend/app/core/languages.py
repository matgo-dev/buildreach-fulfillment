"""报价语言集合(单一源头)。

`SUPPORTED_QUOTE_LANGUAGES` 是 zh/en/sw 值域的唯一权威源头;客户三选一存
(customers.quote_language),报价单/行继承。校验走应用层(派生自本常量),
DB 列只是 VARCHAR、不内联枚举副本(避免与本常量并列两份)。
"""
from __future__ import annotations

SUPPORTED_QUOTE_LANGUAGES: tuple[str, ...] = ("zh", "en", "sw")

# 客户未指定报价语言时的缺省(M1 内容纯中文)。
DEFAULT_QUOTE_LANGUAGE: str = "zh"


def is_supported_quote_language(lang: str) -> bool:
    return lang in SUPPORTED_QUOTE_LANGUAGES
