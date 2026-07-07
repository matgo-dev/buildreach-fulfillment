"""系统消息 key 全集 — 前端翻译文件必须覆盖所有 key。

命名规范:error.<module>.<specific_error>
"""


class MessageKey:
    # auth
    INVALID_CREDENTIALS = "error.auth.invalid_credentials"
    ACCOUNT_LOCKED = "error.auth.account_locked"
    TOKEN_EXPIRED = "error.auth.token_expired"
    PERMISSION_DENIED = "error.auth.permission_denied"
    NOT_AUTHENTICATED = "error.auth.not_authenticated"

    ACCOUNT_DISABLED = "error.auth.account_disabled"
    PASSWORD_CHANGE_REQUIRED = "error.auth.password_change_required"

    # validation
    VALIDATION_FAILED = "error.validation.failed"
    MULTIPLE_VALIDATION_ERRORS = "error.validation.multiple_errors"

    # general
    NOT_FOUND = "error.general.not_found"
    INTERNAL_ERROR = "error.general.internal_error"
    RATE_LIMITED = "error.general.rate_limited"
    CONFLICT = "error.general.conflict"

    # general — 兜底处理器
    CLIENT_ERROR = "error.general.client_error"
    VALIDATION_REQUEST_BODY = "error.validation.request_body"

    # business
    SUPPLIER_ALREADY_REGISTERED = "error.business.supplier_already_registered"
    EMAIL_ALREADY_REGISTERED = "error.business.email_already_registered"
    PHONE_ALREADY_REGISTERED = "error.business.phone_already_registered"

    # buyer registration — 买方注册 4092x / 4220x
    PHONE_FORMAT_INVALID = "error.auth.phone_format_invalid"
    PHONE_REGION_UNSUPPORTED = "error.auth.phone_region_unsupported"
    BUYER_PHONE_FORMAT = "buyer.register.phone_format"
    BUYER_PASSWORD_RULE = "buyer.register.password_rule"
    BUYER_CATEGORY_REQUIRED = "buyer.register.category_required"
    BUYER_CATEGORY_INVALID = "buyer.register.category_invalid"
    BUYER_IMAGE_COUNT = "buyer.register.image_count"
    BUYER_IMAGE_FORMAT = "buyer.register.image_format"
    BUYER_IMAGE_SIZE = "buyer.register.image_size"
    BUYER_ADDRESS_REQUIRED = "buyer.register.address_required"
    BUYER_STOREFRONT_REQUIRED = "buyer.register.storefront_required"
    BUYER_LICENSE_IMAGE_INVALID = "buyer.register.license_image_invalid"
    BUYER_PREF_CATEGORY_INVALID = "buyer.pref.category_invalid"

    # product — 商品模块 402xx
    PRODUCT_INVALID_STATUS = "error.product.invalid_status"
    PRODUCT_SPU_CODE_EXISTS = "error.product.spu_code_exists"
    PRODUCT_SKU_CODE_EXISTS = "error.product.sku_code_exists"
    PRODUCT_PUBLISH_VALIDATION_FAILED = "error.product.publish_validation_failed"
    PRODUCT_ONLY_DRAFT_DELETABLE = "error.product.only_draft_deletable"
    PRODUCT_ILLEGAL_TRANSITION = "error.product.illegal_transition"
    PRODUCT_NOT_EDITABLE = "error.product.not_editable"
    PRODUCT_SUPPLIER_ALREADY_BOUND = "error.product.supplier_already_bound"
    PRODUCT_MAX_IMAGES_EXCEEDED = "error.product.max_images_exceeded"
    PRODUCT_IMAGE_FORMAT_INVALID = "error.product.image_format_invalid"
    PRODUCT_IMAGE_TOO_LARGE = "error.product.image_too_large"
    PRODUCT_IMAGE_TOO_SMALL = "error.product.image_too_small"
    PRODUCT_PRICE_TIER_FIRST_MIN_QTY = "error.product.price_tier_first_min_qty"
    PRODUCT_PRICE_TIER_MAX_NULL_NOT_LAST = "error.product.price_tier_max_null_not_last"
    PRODUCT_PRICE_TIER_NOT_CONTINUOUS = "error.product.price_tier_not_continuous"
    PRODUCT_PRICE_TIER_PRICE_NOT_DECREASING = "error.product.price_tier_price_not_decreasing"
    PRODUCT_SKU_NOT_IN_PRODUCT = "error.product.sku_not_in_product"
    PRODUCT_ATTR_KEY_NOT_IN_TEMPLATE = "error.product.attr_key_not_in_template"
    PRODUCT_REQUIRED_ATTR_MISSING = "error.product.required_attr_missing"
    PRODUCT_ATTR_SCOPE_MISMATCH = "error.product.attr_scope_mismatch"
    PRODUCT_CATEGORY_NOT_LEAF = "error.product.category_not_leaf"
    PRODUCT_INVALID_RANGE = "error.product.invalid_range"
    PRODUCT_IMAGE_NOT_OWNED = "error.product.image_not_owned"

    # cart — 购物车模块 405xx
    CART_SKU_NOT_PURCHASABLE = "error.cart.sku_not_purchasable"
    CART_PRODUCT_NOT_AVAILABLE = "error.cart.product_not_available"
    CART_QUANTITY_INVALID = "error.cart.quantity_invalid"
    CART_ITEM_NOT_FOUND = "error.cart.item_not_found"
    BUYER_ORG_REQUIRED = "error.cart.buyer_org_required"
    CART_DUPLICATE_VARIANT = "error.cart.duplicate_variant"

    # rfq — 询价单模块 405xx
    RFQ_NO_VALID_ITEMS = "error.rfq.no_valid_items"
    RFQ_ITEM_NOT_PURCHASABLE = "error.rfq.item_not_purchasable"
    RFQ_NOT_FOUND = "error.rfq.not_found"
    RFQ_STATE_INVALID = "error.rfq.state_invalid"
    RFQ_DUPLICATE_SKU = "error.rfq.duplicate_sku"
    RFQ_SOURCE_NOT_ALLOWED = "error.rfq.source_not_allowed"
    RFQ_NO_GENERATION_FAILED = "error.rfq.no_generation_failed"
    RFQ_ALREADY_CLAIMED = "error.rfq.already_claimed"
    RFQ_ITEM_NOT_FOUND = "error.rfq.item_not_found"
    RFQ_NOT_ASSIGNED_TO_YOU = "error.rfq.not_assigned_to_you"
    RFQ_MIN_ONE_ITEM = "error.rfq.min_one_item"
    RFQ_NO_QUOTE_TO_EXPORT = "error.rfq.no_quote_to_export"
    RFQ_ITEMS_OR_REMARK_REQUIRED = "error.rfq.items_or_remark_required"

    # attachment — 附件模块 405xx
    ATTACHMENT_TOO_MANY = "error.attachment.too_many"
    ATTACHMENT_TYPE_NOT_ALLOWED = "error.attachment.type_not_allowed"
    ATTACHMENT_TOO_LARGE = "error.attachment.too_large"
    ATTACHMENT_NOT_FOUND = "error.attachment.not_found"
    ATTACHMENT_ALREADY_LINKED = "error.attachment.already_linked"
    ATTACHMENT_ORPHAN_QUOTA = "error.attachment.orphan_quota"

    # quote — 报价模块 405xx
    QUOTE_RFQ_STATE_INVALID = "error.quote.rfq_state_invalid"
    QUOTE_NOT_FOUND = "error.quote.not_found"
    QUOTE_ITEM_MISMATCH = "error.quote.item_mismatch"
    QUOTE_LINES_INCOMPLETE = "error.quote.lines_incomplete"
    QUOTE_LINE_NO_PRICE = "error.quote.line_no_price"