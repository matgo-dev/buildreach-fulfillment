"""红线脱敏单点 helper 单测(采购价/金额对无 read_cost 者置 null)。

全仓首个字段级脱敏机制:后端置 null(非仅前端隐藏)。单一 helper,所有响应出口经它。
"""
from app.rbac.redaction import (
    PO_COST_FIELDS,
    PO_LINE_COST_FIELDS,
    redact_cost,
)


def test_redact_nulls_cost_fields_when_no_permission():
    """无 read_cost:payload 中的成本字段被置 null,其它字段原样。"""
    payload = {"id": 1, "no": "PO2026070001", "total_amount": 999.5, "currency": "USD"}
    out = redact_cost(payload, PO_COST_FIELDS, can_see_cost=False)
    assert out["total_amount"] is None
    assert out["id"] == 1 and out["no"] == "PO2026070001" and out["currency"] == "USD"


def test_redact_passthrough_when_permitted():
    """有 read_cost:payload 原样返回,成本字段保留真值。"""
    payload = {"id": 1, "total_amount": 999.5}
    out = redact_cost(payload, PO_COST_FIELDS, can_see_cost=True)
    assert out["total_amount"] == 999.5


def test_redact_line_cost_fields():
    """行级成本字段集:unit_price / line_total 一起脱敏。"""
    line = {"id": 7, "sku_id": 3, "unit_price": 12.5, "qty": 4, "line_total": 50.0}
    out = redact_cost(line, PO_LINE_COST_FIELDS, can_see_cost=False)
    assert out["unit_price"] is None and out["line_total"] is None
    assert out["qty"] == 4  # 数量非红线,保留


def test_redact_does_not_mutate_input():
    """脱敏返回新 dict,不就地改传入 payload(防调用方复用同一 dict 泄露)。"""
    payload = {"total_amount": 100.0}
    redact_cost(payload, PO_COST_FIELDS, can_see_cost=False)
    assert payload["total_amount"] == 100.0


def test_redact_ignores_absent_fields():
    """字段不在 payload 时不报错(投影可能不含某成本键)。"""
    out = redact_cost({"id": 1}, PO_COST_FIELDS, can_see_cost=False)
    assert out == {"id": 1}


# ---- 三处红线出口在构造工厂层脱敏(列表/详情行/嵌套 related_po),验决策点单一 ----


def _sample_line():
    from types import SimpleNamespace
    return SimpleNamespace(
        id=1, purchase_order_id=2, sku_id=3, source_sales_order_line_id=4,
        name_snapshot="x", spec_text_snapshot="", unit_snapshot="ton",
        unit_price=7.5, qty=3, line_total=22.5, language="zh", sort_order=0, remark=None)


def test_line_out_factory_redacts_without_cost():
    from app.schemas.purchase_order import PurchaseOrderLineOut
    d = PurchaseOrderLineOut.build(_sample_line(), can_see_cost=False)
    assert d["unit_price"] is None and d["line_total"] is None
    assert float(d["qty"]) == 3  # 数量非红线
    d2 = PurchaseOrderLineOut.build(_sample_line(), can_see_cost=True)
    assert float(d2["unit_price"]) == 7.5 and float(d2["line_total"]) == 22.5


def test_list_item_factory_redacts_without_cost():
    from datetime import datetime

    from app.schemas.purchase_order import PurchaseOrderListItem
    item = {"id": 1, "no": "PO2026070001", "source_sales_order_id": 5,
            "source_sales_order_no": "SO2026070001", "supplier_id": 9,
            "supplier_display": "供应商甲", "status": "DRAFT", "currency": "USD",
            "total_amount": 99.9, "line_count": 1, "created_at": datetime(2026, 7, 15)}
    assert PurchaseOrderListItem.build(item, can_see_cost=False)["total_amount"] is None
    assert PurchaseOrderListItem.build(item, can_see_cost=True)["total_amount"] == 99.9


def test_related_po_factory_redacts_without_cost():
    from app.schemas.purchase_order import RelatedPurchaseOrderItem
    item = {"id": 1, "no": "PO2026070001", "status": "CANCELLED", "supplier_id": 9,
            "supplier_display": "供应商甲", "currency": "USD", "total_amount": 14.0}
    assert RelatedPurchaseOrderItem.build(item, can_see_cost=False)["total_amount"] is None
    # 供应商身份保留(related_po 结构本身仅 purchase:read 端点下发;金额才是字段级红线)
    assert RelatedPurchaseOrderItem.build(item, can_see_cost=False)["supplier_display"] == "供应商甲"
    assert RelatedPurchaseOrderItem.build(item, can_see_cost=True)["total_amount"] == 14.0
