"""业务编号:scope 单一源头(身份键 + 格式配置)+ 纯格式化。真正的号由编号服务 app/services/numbering.py 发。

SAP/Odoo 口径:前缀 + 零填充。主数据全局号段、中性不透明(不编码属性);
单据 = 前缀 + 年月 + 期内序号。
"""
from __future__ import annotations

from enum import Enum


class NumberScope(str, Enum):
    """业务编号 scope —— 唯一注册处(身份键 + 格式)。加单据类型 = 加一行,别在别处再列一份。

    成员名/值 = scope 身份键(存 number_sequence.scope);继承 str → 成员可直接当字符串用
    (DB 写入 / 比较 / f-string / allocate 入参)。每行 = (身份键, 前缀, 补零位宽, periodic):
    periodic=True 时序号前插 period(年月),供单据人工识别/归档/降跨期冲突;主数据 periodic=False。
    """
    SKU            = "SKU",            "SKU", 8, False
    SPU            = "SPU",            "SPU", 8, False
    CUSTOMER       = "CUSTOMER",       "C",   6, False
    SUPPLIER       = "SUPPLIER",       "V",   6, False  # 供应商主数据全局号,中性不透明(同 CUSTOMER 档次)
    QUOTATION      = "QUOTATION",      "Q",   4, True
    SALES_ORDER    = "SALES_ORDER",    "SO",  4, True
    PURCHASE_ORDER = "PURCHASE_ORDER", "PO",  4, True   # 采购单:前缀+年月+期内序号,PO{YYYYMM}{seq:04d}
    INBOUND        = "INBOUND",        "IN",  4, True   # 入库单:IN{YYYYMM}{seq:04d}(应付款账层无业务号,见契约 D9)

    def __new__(cls, value: str, prefix: str, pad: int, periodic: bool):
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.prefix, obj.pad, obj.periodic = prefix, pad, periodic
        return obj


def format_code(scope: NumberScope | str, seq: int, period: str = "") -> str:
    """按 scope 配置格式化业务号。scope 传枚举成员或其字符串;未知 scope 抛 ValueError。"""
    scope = NumberScope(scope)
    mid = period if scope.periodic else ""
    return f"{scope.prefix}{mid}{seq:0{scope.pad}d}"
