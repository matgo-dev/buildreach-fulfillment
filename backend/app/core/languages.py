"""报价语言集合(单一源头)。

`SUPPORTED_QUOTE_LANGUAGES` 是 zh/en/sw 值域的唯一权威源头;客户三选一存
(customers.quote_language),报价单/行继承。校验走应用层(派生自本常量),
DB 列只是 VARCHAR、不内联枚举副本(避免与本常量并列两份)。
"""
from __future__ import annotations

SUPPORTED_QUOTE_LANGUAGES: tuple[str, ...] = ("zh", "en", "sw")

# 客户未指定报价语言时的缺省(M1 内容纯中文)。
DEFAULT_QUOTE_LANGUAGE: str = "zh"

# 内部界面语言 —— 与上面的**报价语言**是两个不同的东西,别混用:
#   报价语言 = 发给客户的单据语言(报价单/形式发票等对外输出),存在单据上、随客户走;
#   界面语言 = 内部运营看的列表/详情渲染语言,随**使用系统的人**走。
# 内部读投影(库存页等)一律按本常量渲染;拿单据语言渲染内部列表会中英混排
# (实测:库存单位列一行「件」一行「bag」)。本平台是中文运营界面,故恒为 zh;
# 将来真出现多语言操作员再改成按用户 locale 取,消费者在此单点收敛。
INTERNAL_UI_LANGUAGE: str = "zh"


def is_supported_quote_language(lang: str) -> bool:
    return lang in SUPPORTED_QUOTE_LANGUAGES
