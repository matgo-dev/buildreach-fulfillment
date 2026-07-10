"""业务编号格式化(纯函数;真正的号由编号服务 app/services/numbering.py 发)。

SAP/Odoo 口径:前缀 + 零填充。主数据全局号段、中性不透明(不编码商品属性);
单据 = 前缀 + 年月 + 期内序号。本系统全内部、编号不承载可变业务信息。
"""
from __future__ import annotations


def format_sku_code(seq: int) -> str:
    return f"SKU{seq:08d}"


def format_customer_code(seq: int) -> str:
    return f"C{seq:06d}"


def format_quote_no(period: str, seq: int) -> str:
    """period 形如 '202607'(UTC 年月,由调用方传入);seq 为该年月期内序号。"""
    return f"Q{period}{seq:04d}"
