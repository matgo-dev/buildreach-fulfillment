"""红线字段脱敏 —— 单点 helper(全仓字段级脱敏机制)。

两类红线共用同一套脱敏机制(`redact_fields`),各自门控谓词 + 字段集不同:
- 成本红线(采购价 / 采购金额):gate=purchase:read_cost,承载于采购单 / 入库单 / SKU。
- 售价红线(客户售价 / 成交额):gate=receivable:read,承载于销售单头 / 行。

对无权者**后端置 null**(非仅前端隐藏):列表、详情、嵌套关联响应都不下发真值。
可见性判断下沉到响应 schema 构造工厂(`*.build(...)`,单点经 `redact_fields`),
让「新出口忘记脱敏而裸露红线」在结构上更难发生,而非 dump 后再 patch。
"""
from __future__ import annotations

from app.core.dependencies import CurrentUser
from app.rbac.constants import Permissions
from app.rbac.guards import has_permission

# ---- 成本红线(采购价)字段集(按承载层分组)----
PO_COST_FIELDS = frozenset({"total_amount"})          # 采购单头:金额合计
PO_LINE_COST_FIELDS = frozenset({"unit_price", "line_total"})  # 采购单行:单价 + 行额
SKU_COST_FIELDS = frozenset({"reference_price"})      # SKU:内部采购参考价

# ---- 售价红线(客户售价)字段集 ----
SO_PRICE_FIELDS = frozenset({"total_amount"})               # 销售单头:成交总额
SO_LINE_PRICE_FIELDS = frozenset({"unit_price", "line_total"})  # 销售单行:对客单价 + 行额


def can_see_cost(current: CurrentUser) -> bool:
    """成本红线可见性单点判定(purchase:read_cost)。采购单/入库单/销售单详情内嵌 PO 等
    所有「无权→成本置 null」出口共用此谓词,不散内联判断。
    注意:商品域 reference_price 的可见性走 PRODUCT_MANAGE(另一权限点,语义不同),
    调用方直接用 has_permission,不并入本判定。"""
    return has_permission(current, Permissions.PURCHASE_READ_COST)


def can_see_price(current: CurrentUser) -> bool:
    """客户售价红线可见性单点判定(receivable:read)。销售单头/行售价所有
    「无权→售价置 null」出口共用此谓词。SALES / FINANCE 持有;PURCHASER / LOGISTICS 不持
    (见 permissions_config:应收=客户售价整域,采购/物流不授)。"""
    return has_permission(current, Permissions.RECEIVABLE_READ)


def redact_fields(payload: dict, fields, *, visible: bool) -> dict:
    """有权(visible) → 原样;无权 → 返回新 dict,把 fields 中出现在 payload 的键置 None。

    返回新 dict 不就地修改入参(防调用方复用同一 dict 时真值泄露);字段不在 payload 时跳过。
    成本 / 售价两类红线共用此单一脱敏机制。
    """
    if visible:
        return payload
    return {**payload, **{k: None for k in fields if k in payload}}
