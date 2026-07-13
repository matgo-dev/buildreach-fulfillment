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
    assert QUOTATION_TRANSITIONS[QuotationStatus.CONVERTED] == set()
    assert QUOTATION_TRANSITIONS[QuotationStatus.VOID] == set()


def test_editable_deletable_voidable_sets():
    # 删=硬删仅草稿;作废=草稿/锁档;编辑仅草稿(锁档后只读)。
    assert QUOTATION_EDITABLE == {"DRAFT"}
    assert QUOTATION_DELETABLE == {"DRAFT"}
    assert QUOTATION_VOIDABLE == {"DRAFT", "LOCKED"}
