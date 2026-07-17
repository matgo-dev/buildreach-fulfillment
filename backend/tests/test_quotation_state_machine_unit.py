"""报价状态机常量单一源头(model 层)单元测试。纯 Python,无 DB。"""
from app.db.models.quotation import (
    QUOTATION_DELETABLE,
    QUOTATION_EDITABLE,
    QUOTATION_TRANSITIONS,
    QUOTATION_VOIDABLE,
    QuotationStatus,
)


def test_status_values_are_english_codes():
    assert QuotationStatus.DRAFT == "DRAFT"
    assert QuotationStatus.LOCKED == "LOCKED"
    assert QuotationStatus.CONVERTED == "CONVERTED"
    assert QuotationStatus.VOID == "VOID"
    assert QuotationStatus.ALL == ("DRAFT", "LOCKED", "CONVERTED", "VOID")


def test_transitions_matrix():
    # 草稿可锁档或作废;锁档可解锁/转销售/作废;转销售、作废是终态。
    assert QUOTATION_TRANSITIONS[QuotationStatus.DRAFT] == {"LOCKED", "VOID"}
    assert QUOTATION_TRANSITIONS[QuotationStatus.LOCKED] == {"DRAFT", "CONVERTED", "VOID"}
    # CONVERTED→LOCKED = SO 取消回退(仅取消服务内部走;公开 lock 端点已收紧仅 DRAFT)
    assert QUOTATION_TRANSITIONS[QuotationStatus.CONVERTED] == {QuotationStatus.LOCKED}
    assert QUOTATION_TRANSITIONS[QuotationStatus.VOID] == set()


def test_editable_deletable_voidable_sets():
    # 删=硬删仅草稿;编辑仅草稿(锁档后只读)。
    assert QUOTATION_EDITABLE == {"DRAFT"}
    assert QUOTATION_DELETABLE == {"DRAFT"}
    # VOIDABLE 派生自矩阵(非并列副本):值恒 = 目标含 VOID 的态 —— 矩阵一改它自动跟随,不漂移。
    assert QUOTATION_VOIDABLE == {
        s for s, t in QUOTATION_TRANSITIONS.items() if QuotationStatus.VOID in t}
    assert QUOTATION_VOIDABLE == {"DRAFT", "LOCKED"}  # 当前矩阵下的具体值
