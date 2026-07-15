"""红线字段脱敏 —— 单点 helper(全仓首个字段级脱敏机制)。

成本红线(采购价 / 采购金额)对无 `purchase:read_cost` 权限者**后端置 null**(非仅前端隐藏):
列表、详情、嵌套关联响应都不下发真值。所有响应出口经此单一 helper,不散 if/else;
可见性判断下沉到响应 schema 构造工厂(PurchaseOrderOut.build 等),让「新出口忘记脱敏而裸露成本」
在结构上更难发生(入库步会新增读 PO 的出口)。
"""
from __future__ import annotations

# 成本字段集(单一源头,按承载层分组)。
PO_COST_FIELDS = frozenset({"total_amount"})          # 采购单头:金额合计
PO_LINE_COST_FIELDS = frozenset({"unit_price", "line_total"})  # 采购单行:单价 + 行额


def redact_cost(payload: dict, fields, *, can_see_cost: bool) -> dict:
    """有权 → 原样;无权 → 返回新 dict,把 fields 中出现在 payload 的键置 None。

    返回新 dict 不就地修改入参(防调用方复用同一 dict 时真值泄露);字段不在 payload 时跳过。
    """
    if can_see_cost:
        return payload
    return {**payload, **{k: None for k in fields if k in payload}}
