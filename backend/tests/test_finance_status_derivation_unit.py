"""收付款单派生状态单测(纯逻辑,无 DB)。

收款四态:UNCLAIMED(客户未知,独立于金额)/ UNALLOCATED / PARTIALLY_ALLOCATED / FULLY_ALLOCATED。
付款三态:无 UNCLAIMED(supplier 必填,主动付给已知方)。
判序对齐账层 derive_*_status:先判 FULLY(allocated>=amount,含 0 金额边界),再判 UNALLOCATED。
"""
from app.db.models.payment import PaymentStatus, derive_payment_status
from app.db.models.receipt import ReceiptStatus, derive_receipt_status


class TestReceiptStatus:
    def test_unclaimed_when_customer_none_regardless_of_amount(self):
        # 客户未知 = UNCLAIMED,即便金额已全额(理论上未认领不可核销,此为纯函数边界)
        assert derive_receipt_status(None, "100.00", "0") == ReceiptStatus.UNCLAIMED
        assert derive_receipt_status(None, "100.00", "100.00") == ReceiptStatus.UNCLAIMED

    def test_fully_allocated_when_allocated_ge_amount(self):
        assert derive_receipt_status(7, "100.00", "100.00") == ReceiptStatus.FULLY_ALLOCATED

    def test_unallocated_when_zero(self):
        # 已认领但一分未核销 = 全额预收
        assert derive_receipt_status(7, "100.00", "0") == ReceiptStatus.UNALLOCATED

    def test_partially_allocated(self):
        assert derive_receipt_status(7, "100.00", "40.00") == ReceiptStatus.PARTIALLY_ALLOCATED

    def test_fully_takes_precedence_over_unallocated_at_zero_amount(self):
        # amount>0 CHECK 撑着,但派生不依赖它:0 已核销 vs 0 金额,先判 FULLY 不会误判
        # (收款 amount CHECK>0,此为判序稳健性验证,对齐账层 0 金额单边界)
        assert derive_receipt_status(7, "0.00", "0") == ReceiptStatus.FULLY_ALLOCATED


class TestPaymentStatus:
    def test_no_unclaimed_state(self):
        assert "UNCLAIMED" not in PaymentStatus.ALL

    def test_fully_allocated(self):
        assert derive_payment_status("100.00", "100.00") == PaymentStatus.FULLY_ALLOCATED

    def test_unallocated(self):
        assert derive_payment_status("100.00", "0") == PaymentStatus.UNALLOCATED

    def test_partially_allocated(self):
        assert derive_payment_status("100.00", "40.00") == PaymentStatus.PARTIALLY_ALLOCATED
