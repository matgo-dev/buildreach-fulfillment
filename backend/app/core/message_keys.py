"""系统消息 key 全集 — 前端翻译文件必须覆盖所有 key。

命名规范:error.<module>.<specific_error>
"""


class MessageKey:
    # auth
    INVALID_CREDENTIALS = "error.auth.invalid_credentials"
    ACCOUNT_LOCKED = "error.auth.account_locked"
    PERMISSION_DENIED = "error.auth.permission_denied"
    NOT_AUTHENTICATED = "error.auth.not_authenticated"

    ACCOUNT_DISABLED = "error.auth.account_disabled"
    PASSWORD_CHANGE_REQUIRED = "error.auth.password_change_required"

    # validation
    VALIDATION_FAILED = "error.validation.failed"

    # general
    NOT_FOUND = "error.general.not_found"
    INTERNAL_ERROR = "error.general.internal_error"
    CONFLICT = "error.general.conflict"

    # general — 兜底处理器
    CLIENT_ERROR = "error.general.client_error"

    # sku
    SPEC_CONTRACT = "error.sku.spec_contract"

    # product 生命周期(SPU 状态机)
    PRODUCT_NOT_EDITABLE = "error.product.not_editable"
    PRODUCT_ILLEGAL_TRANSITION = "error.product.illegal_transition"
    PRODUCT_INCOMPLETE = "error.product.incomplete"

    # quotation 报价(模块段 14)
    QUOTATION_NOT_DRAFT = "error.quotation.not_draft"
    QUOTATION_EMPTY_LINES = "error.quotation.empty_lines"
    QUOTATION_INVALID_TRANSITION = "error.quotation.invalid_transition"
    QUOTATION_CANNOT_UNLOCK_CONVERTED = "error.quotation.cannot_unlock_converted"
    QUOTATION_EDIT_CONFLICT = "error.quotation.edit_conflict"
    QUOTATION_INVALID_LINE = "error.quotation.invalid_line"
    QUOTATION_CANNOT_VOID = "error.quotation.cannot_void"
    QUOTATION_INVALID_SALESPERSON = "error.quotation.invalid_salesperson"
    QUOTATION_CANNOT_CONVERT = "error.quotation.cannot_convert"

    # supplier 供应商(模块段 15)
    SUPPLIER_NOT_FOUND = "error.supplier.not_found"
    SUPPLIER_CODE_CONFLICT = "error.supplier.code_conflict"
    SUPPLIER_INACTIVE = "error.supplier.inactive"

    # purchase_order 采购单(模块段 16)
    PURCHASE_ORDER_NOT_FOUND = "error.purchase_order.not_found"
    PURCHASE_ORDER_INVALID_TRANSITION = "error.purchase_order.invalid_transition"
    PURCHASE_ORDER_OVER_PURCHASE = "error.purchase_order.over_purchase"
    PURCHASE_ORDER_SOURCE_INVALID = "error.purchase_order.source_invalid"
    PURCHASE_ORDER_EDIT_CONFLICT = "error.purchase_order.edit_conflict"
    PURCHASE_ORDER_SUPPLIER_INACTIVE = "error.purchase_order.supplier_inactive"
    PURCHASE_ORDER_NOT_DRAFT = "error.purchase_order.not_draft"
    PURCHASE_ORDER_EMPTY = "error.purchase_order.empty"
    PURCHASE_ORDER_HAS_ACTIVE_INBOUND = "error.purchase_order.has_active_inbound"

    # inbound_order 入库单 / payable 应付款(模块段 17)
    INBOUND_ORDER_NOT_FOUND = "error.inbound_order.not_found"
    INBOUND_ORDER_SOURCE_PO_INVALID = "error.inbound_order.source_po_invalid"
    INBOUND_ORDER_OVER_RECEIPT = "error.inbound_order.over_receipt"
    INBOUND_ORDER_INVALID_TRANSITION = "error.inbound_order.invalid_transition"
    INBOUND_ORDER_NOT_IN_TRANSIT = "error.inbound_order.not_in_transit"
    INBOUND_ORDER_LINE_NOT_IN_PO = "error.inbound_order.line_not_in_po"
    INBOUND_ORDER_EMPTY = "error.inbound_order.empty"
    PAYABLE_ALLOCATED_CANNOT_UNRECEIVE = "error.payable.allocated_cannot_unreceive"
