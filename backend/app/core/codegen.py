"""业务编号格式化(纯函数;真正的号由编号服务 app/services/numbering.py 发)。

SAP/Odoo 口径:前缀 + 零填充。主数据全局号段、中性不透明(不编码属性);
单据 = 前缀 + 年月 + 期内序号。scope 与 numbering.NumberScope 对齐。
"""
from __future__ import annotations

# scope → 格式配置。periodic=True 时序号前插 period(年月)。
CODE_FORMATS: dict[str, dict] = {
    "SKU":       {"prefix": "SKU", "pad": 8, "periodic": False},
    "SPU":       {"prefix": "SPU", "pad": 8, "periodic": False},
    "CUSTOMER":  {"prefix": "C",   "pad": 6, "periodic": False},
    "QUOTATION": {"prefix": "Q",   "pad": 4, "periodic": True},
}


def format_code(scope: str, seq: int, period: str = "") -> str:
    """按 scope 配置格式化业务号。未知 scope 抛 KeyError。"""
    fmt = CODE_FORMATS[scope]
    body = f"{seq:0{fmt['pad']}d}"
    mid = period if fmt["periodic"] else ""
    return f"{fmt['prefix']}{mid}{body}"
