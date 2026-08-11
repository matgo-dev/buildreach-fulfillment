"""报价异常契约(模块段 MM=14 → 414xx)单元测试。"""
from app.core.exceptions import (
    QuotationCannotUnlockConvertedError,
    QuotationEditConflictError,
    QuotationEmptyLinesError,
    QuotationInvalidLineError,
    QuotationInvalidTransitionError,
    QuotationNotDraftError,
)


def test_not_draft():
    e = QuotationNotDraftError()
    assert e.status_code == 409 and e.biz_code == 41401


def test_empty_lines():
    e = QuotationEmptyLinesError()
    assert e.status_code == 400 and e.biz_code == 41402


def test_invalid_transition():
    e = QuotationInvalidTransitionError()
    assert e.status_code == 409 and e.biz_code == 41403


def test_cannot_unlock_converted():
    e = QuotationCannotUnlockConvertedError()
    assert e.status_code == 409 and e.biz_code == 41404


def test_edit_conflict():
    e = QuotationEditConflictError()
    assert e.status_code == 409 and e.biz_code == 41405


def test_invalid_line():
    e = QuotationInvalidLineError()
    assert e.status_code == 400 and e.biz_code == 41406
