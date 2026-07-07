"""业务异常 + 统一响应格式。

业务码(body.code)与 HTTP status 解耦,仅承载业务语义。

格式 5 位:C MM SS
- C : 4=客户端类, 5=服务端类
- MM: 模块段
- SS: 模块内顺序号(01–99)

模块段位:
  MM | 模块             | 现有码
  00 | 通用与鉴权       | 40001–40009
  01 | 供应商(注册/资质) | 预留
  02 | 商品             | 预留
  03 | 品类             | 预留
  04 | 信用             | 预留(credit 类型化时填)
  05 | 交易(购物车/询价/报价) | 40501–40504
  06–08 | 预留           | —
  09 | 注册冲突聚合     | 40901/40902/40903(前端冻结,沿用)

兜底码:
  40000 = 通用客户端兜底(裸 HTTPException 降级)
  50000 = 通用服务端兜底(未处理异常)

既存例外(不纳入 4MMSS,标注为 422 派生):
  42200 = 请求体校验失败(handler 级,前端冻结)

成功码: 0
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.core.message_keys import MessageKey


class BusinessError(HTTPException):
    """所有业务异常的基类。"""

    def __init__(
        self,
        http_status: int,
        biz_code: int,
        message: str,
        data: Any = None,
        message_key: str | None = None,
        message_params: dict | None = None,
    ):
        super().__init__(status_code=http_status, detail=message)
        self.biz_code = biz_code
        self.biz_message = message
        self.biz_data = data
        self.message_key = message_key
        self.message_params = message_params


class InvalidCredentialsError(BusinessError):
    def __init__(self, message: str = "Invalid credentials"):
        super().__init__(status.HTTP_401_UNAUTHORIZED, 40001, message, message_key=MessageKey.INVALID_CREDENTIALS)


class TooManyAttemptsError(BusinessError):
    def __init__(self, message: str = "Too many failed attempts, account locked"):
        super().__init__(status.HTTP_429_TOO_MANY_REQUESTS, 40002, message, message_key=MessageKey.ACCOUNT_LOCKED)


class PermissionDeniedError(BusinessError):
    def __init__(self, message: str = "Permission denied"):
        super().__init__(status.HTTP_403_FORBIDDEN, 40003, message, message_key=MessageKey.PERMISSION_DENIED)


class NotAuthenticatedError(BusinessError):
    def __init__(self, message: str = "Not authenticated"):
        super().__init__(status.HTTP_401_UNAUTHORIZED, 40004, message, message_key=MessageKey.NOT_AUTHENTICATED)


class AccountDisabledError(BusinessError):
    def __init__(self, message: str = "Account disabled"):
        super().__init__(status.HTTP_403_FORBIDDEN, 40005, message, message_key=MessageKey.ACCOUNT_DISABLED)


class AccountDeactivatedError(BusinessError):
    def __init__(self, message: str = "Account has been deactivated"):
        super().__init__(status.HTTP_403_FORBIDDEN, 40305, message, message_key=MessageKey.ACCOUNT_DISABLED)


class ValidationFailedError(BusinessError):
    def __init__(self, message: str = "Validation failed"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 40006, message, message_key=MessageKey.VALIDATION_FAILED)


class PasswordChangeRequiredError(BusinessError):
    """must_change_password=True 的账号访问非豁免端点时抛出。"""

    def __init__(self, message: str = "Password change required"):
        super().__init__(status.HTTP_403_FORBIDDEN, 40007, message, message_key=MessageKey.PASSWORD_CHANGE_REQUIRED)


class ConflictError(BusinessError):
    def __init__(self, message: str = "Resource conflict"):
        super().__init__(status.HTTP_409_CONFLICT, 40009, message, message_key=MessageKey.CONFLICT)


class PhoneFormatError(BusinessError):
    """42221 — 手机号格式非法。"""
    def __init__(self, message: str = "Invalid phone number format"):
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY, 42221, message,
            message_key=MessageKey.PHONE_FORMAT_INVALID,
        )


class PhoneUnsupportedRegionError(BusinessError):
    """42222 — 手机号所属国家不在支持范围。"""
    def __init__(self, message: str = "Phone number region not supported"):
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY, 42222, message,
            message_key=MessageKey.PHONE_REGION_UNSUPPORTED,
        )


class SupplierAlreadyRegisteredError(BusinessError):
    """供应商重复入驻(PRD v1.4 Δ9)。

    code=40901(数字),前端识别错误必须用数字比较,严禁字符串比较异常类名。
    message 沿用 PRD v1.3 §5.3 标准化文案,不暴露 owner / 公司名。
    """

    def __init__(
        self,
        message: str = "当前企业已在平台注册。如需加入,请联系您所在企业的平台管理员添加账号。",
    ):
        super().__init__(status.HTTP_409_CONFLICT, 40901, message, message_key=MessageKey.SUPPLIER_ALREADY_REGISTERED)


class EmailAlreadyRegisteredError(BusinessError):
    """邮箱已被注册(PRD v1.5 Δ2,code=40902)。单独抛出场景。"""

    def __init__(
        self,
        message: str = "该邮箱已注册,请直接登录或更换邮箱",
    ):
        super().__init__(
            status.HTTP_409_CONFLICT,
            40902,
            message,
            data={"errors": [{"field": "email", "code": 40902, "message": message}]},
            message_key=MessageKey.EMAIL_ALREADY_REGISTERED,
        )


class PhoneAlreadyRegisteredError(BusinessError):
    """手机号已被注册(PRD v1.5 Δ2,code=40903)。单独抛出场景。"""

    def __init__(
        self,
        message: str = "该手机号已注册,请直接登录或更换手机号",
    ):
        super().__init__(
            status.HTTP_409_CONFLICT,
            40903,
            message,
            data={"errors": [{"field": "phone", "code": 40903, "message": message}]},
            message_key=MessageKey.PHONE_ALREADY_REGISTERED,
        )


class MultipleValidationError(BusinessError):
    """多错误并发场景(PRD v1.5 Δ3)。
    顶层 code 按优先级取:40901(注册号重) > 40902(邮箱重) > 40903(手机号重)。
    无论 errors 长度为 1 还是 N,response.data.errors 都返回数组。
    """

    # 数字优先级:索引小者优先,作为顶层 code 来源
    _PRIORITY = (40901, 40902, 40903, 40921, 40922)

    def __init__(self, errors: list[dict]):
        if not errors:
            # 业务上不该走到这里;防御性兜底
            raise ValueError("MultipleValidationError requires at least one error")
        # 取优先级最高的错误码作为顶层 code
        codes = {e["code"] for e in errors}
        top_code = next((c for c in self._PRIORITY if c in codes), errors[0]["code"])
        if len(errors) == 1:
            top_message = errors[0]["message"]
        else:
            top_message = "请修正以下问题"
        super().__init__(
            status.HTTP_409_CONFLICT,
            top_code,
            top_message,
            data={"errors": errors},
            message_key=MessageKey.MULTIPLE_VALIDATION_ERRORS,
        )


class NotFoundError(BusinessError):
    def __init__(self, message: str = "Not found"):
        super().__init__(status.HTTP_404_NOT_FOUND, 40008, message, message_key=MessageKey.NOT_FOUND)


# ── 商品模块 402xx ──────────────────────────────────────────


class InvalidProductStatusError(BusinessError):
    def __init__(self, status_value: str):
        super().__init__(
            status.HTTP_400_BAD_REQUEST, 40201,
            f"Invalid status: {status_value}",
            message_key=MessageKey.PRODUCT_INVALID_STATUS,
            message_params={"status": status_value},
        )


class SpuCodeExistsError(BusinessError):
    def __init__(self):
        super().__init__(
            status.HTTP_400_BAD_REQUEST, 40202,
            "SPU code already exists",
            message_key=MessageKey.PRODUCT_SPU_CODE_EXISTS,
        )


class SkuCodeExistsError(BusinessError):
    def __init__(self):
        super().__init__(
            status.HTTP_400_BAD_REQUEST, 40203,
            "SKU code already exists",
            message_key=MessageKey.PRODUCT_SKU_CODE_EXISTS,
        )


class PublishValidationFailedError(BusinessError):
    def __init__(self, errors: list[dict[str, object]]):
        # message 用 key 拼接，方便日志；前端靠 errors 结构化翻译
        summary = "; ".join(e.get("key", "") for e in errors)  # type: ignore[union-attr]
        super().__init__(
            status.HTTP_400_BAD_REQUEST, 40204,
            summary,
            message_key=MessageKey.PRODUCT_PUBLISH_VALIDATION_FAILED,
            message_params={"errors": errors},
        )


class OnlyDraftDeletableError(BusinessError):
    def __init__(self):
        super().__init__(
            status.HTTP_400_BAD_REQUEST, 40205,
            "Only DRAFT or INACTIVE products can be deleted",
            message_key=MessageKey.PRODUCT_ONLY_DRAFT_DELETABLE,
        )


class IllegalTransitionError(BusinessError):
    def __init__(self, current: str, target: str):
        super().__init__(
            status.HTTP_400_BAD_REQUEST, 40206,
            f"Cannot transition from {current} to {target}",
            message_key=MessageKey.PRODUCT_ILLEGAL_TRANSITION,
            message_params={"current": current, "target": target},
        )


class ProductNotEditableError(BusinessError):
    def __init__(self, current_status: str):
        super().__init__(
            status.HTTP_400_BAD_REQUEST, 40207,
            f"Product in {current_status} status is not editable. Take it offline first.",
            message_key=MessageKey.PRODUCT_NOT_EDITABLE,
            message_params={"status": current_status},
        )


class SupplierAlreadyBoundError(BusinessError):
    def __init__(self):
        super().__init__(
            status.HTTP_400_BAD_REQUEST, 40206,
            "Supplier already bound to this SKU",
            message_key=MessageKey.PRODUCT_SUPPLIER_ALREADY_BOUND,
        )


class MaxImagesExceededError(BusinessError):
    def __init__(self, max_count: int):
        super().__init__(
            status.HTTP_400_BAD_REQUEST, 40207,
            f"Maximum {max_count} images per product",
            message_key=MessageKey.PRODUCT_MAX_IMAGES_EXCEEDED,
            message_params={"max": max_count},
        )


class ImageFormatInvalidError(BusinessError):
    def __init__(self, allowed: str):
        super().__init__(
            status.HTTP_400_BAD_REQUEST, 40208,
            f"Allowed formats: {allowed}",
            message_key=MessageKey.PRODUCT_IMAGE_FORMAT_INVALID,
            message_params={"formats": allowed},
        )


class ImageTooLargeError(BusinessError):
    def __init__(self):
        super().__init__(
            status.HTTP_400_BAD_REQUEST, 40209,
            "Image size must be under 5MB",
            message_key=MessageKey.PRODUCT_IMAGE_TOO_LARGE,
        )


class ImageTooSmallError(BusinessError):
    def __init__(self):
        super().__init__(
            status.HTTP_400_BAD_REQUEST, 40210,
            "Image too small, minimum 200x200",
            message_key=MessageKey.PRODUCT_IMAGE_TOO_SMALL,
        )


class PriceTierInvalidError(BusinessError):
    """阶梯价校验失败,同码 40211,按子条件分 message_key。"""
    def __init__(
        self,
        message: str,
        message_key: str = MessageKey.PRODUCT_PRICE_TIER_FIRST_MIN_QTY,
        message_params: dict | None = None,
    ):
        super().__init__(
            status.HTTP_400_BAD_REQUEST, 40211,
            message,
            message_key=message_key,
            message_params=message_params,
        )


class SkuNotInProductError(BusinessError):
    def __init__(self, sku_id: int, product_id: int):
        super().__init__(
            status.HTTP_400_BAD_REQUEST, 40212,
            f"SKU {sku_id} does not belong to product {product_id}",
            message_key=MessageKey.PRODUCT_SKU_NOT_IN_PRODUCT,
            message_params={"sku_id": sku_id, "product_id": product_id},
        )


class AttrKeyNotInTemplateError(BusinessError):
    def __init__(self, attr_key: str, category_code: str):
        super().__init__(
            status.HTTP_400_BAD_REQUEST, 40213,
            f"Attribute '{attr_key}' not in template for category '{category_code}'",
            message_key=MessageKey.PRODUCT_ATTR_KEY_NOT_IN_TEMPLATE,
            message_params={"attr_key": attr_key, "category_code": category_code},
        )


class RequiredAttrMissingError(BusinessError):
    def __init__(self, missing_keys: list[str]):
        super().__init__(
            status.HTTP_400_BAD_REQUEST, 40214,
            f"Required attributes missing: {', '.join(missing_keys)}",
            message_key=MessageKey.PRODUCT_REQUIRED_ATTR_MISSING,
            message_params={"keys": ", ".join(missing_keys)},
        )


class AttrScopeMismatchError(BusinessError):
    def __init__(self, attr_key: str, expected_scope: str):
        super().__init__(
            status.HTTP_400_BAD_REQUEST, 40215,
            f"Attribute '{attr_key}' scope should be {expected_scope}",
            message_key=MessageKey.PRODUCT_ATTR_SCOPE_MISMATCH,
            message_params={"attr_key": attr_key, "expected_scope": expected_scope},
        )


class CategoryNotLeafError(BusinessError):
    def __init__(self, category_code: str):
        super().__init__(
            status.HTTP_400_BAD_REQUEST, 40216,
            f"Category '{category_code}' is not a leaf node; only leaf categories are allowed",
            message_key=MessageKey.PRODUCT_CATEGORY_NOT_LEAF,
            message_params={"category_code": category_code},
        )


class ProductRangeInvalidError(BusinessError):
    def __init__(self, min_field: str, max_field: str):
        super().__init__(
            status.HTTP_400_BAD_REQUEST, 40217,
            f"{min_field} must be less than or equal to {max_field}",
            message_key=MessageKey.PRODUCT_INVALID_RANGE,
            message_params={"min_field": min_field, "max_field": max_field},
        )


class ImageNotOwnedError(BusinessError):
    """聚合保存时引用了不属于本商品的 image_id。"""
    def __init__(self, image_id: int, product_id: int):
        super().__init__(
            status.HTTP_400_BAD_REQUEST, 40218,
            f"Image {image_id} does not belong to product {product_id}",
            message_key=MessageKey.PRODUCT_IMAGE_NOT_OWNED,
            message_params={"image_id": image_id, "product_id": product_id},
        )


# ── 交易域 405xx ──────────────────────────────────────────


class CartSkuNotPurchasableError(BusinessError):
    """40501 — SKU 不可购(不存在/未上架/已删/父 SPU 不可购)。"""
    def __init__(self):
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY, 40501,
            "SKU is not purchasable",
            message_key=MessageKey.CART_SKU_NOT_PURCHASABLE,
        )


class CartProductNotAvailableError(BusinessError):
    """40501 — 商品不可购(不存在/未上架/已软删)。"""
    def __init__(self):
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY, 40501,
            "Product is not available for purchase",
            message_key=MessageKey.CART_PRODUCT_NOT_AVAILABLE,
        )


class CartQuantityInvalidError(BusinessError):
    """40502 — 数量非法(≤0 或缺失)。"""
    def __init__(self):
        super().__init__(
            status.HTTP_400_BAD_REQUEST, 40502,
            "Invalid quantity",
            message_key=MessageKey.CART_QUANTITY_INVALID,
        )


class CartItemNotFoundError(BusinessError):
    """40503 — 购物车行不存在(含不属于当前用户,不暴露存在性)。"""
    def __init__(self):
        super().__init__(
            status.HTTP_404_NOT_FOUND, 40503,
            "Cart item not found",
            message_key=MessageKey.CART_ITEM_NOT_FOUND,
        )


class BuyerOrgRequiredError(BusinessError):
    """40504 — 当前用户无可用买方组织。"""
    def __init__(self):
        super().__init__(
            status.HTTP_403_FORBIDDEN, 40504,
            "Active buyer organization required",
            message_key=MessageKey.BUYER_ORG_REQUIRED,
        )


class RfqNoValidItemsError(BusinessError):
    """40505 — 提交无有效行。"""
    def __init__(self):
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY, 40505,
            "No valid items for RFQ submission",
            message_key=MessageKey.RFQ_NO_VALID_ITEMS,
        )


class RfqItemNotPurchasableError(BusinessError):
    """40506 — SKU 不可购(data 列 offending sku)。保留兼容旧调用。"""
    def __init__(self, offending_sku_ids: list[int]):
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY, 40506,
            "Some SKUs are not purchasable",
            data={"offending_sku_ids": offending_sku_ids},
            message_key=MessageKey.RFQ_ITEM_NOT_PURCHASABLE,
        )


class RfqProductNotAvailableError(BusinessError):
    """40506 — 商品不可用（未上架/已下架/已删除）。"""
    def __init__(self, offending_product_ids: list[int]):
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY, 40506,
            "Some products are not available",
            data={"offending_product_ids": offending_product_ids},
            message_key=MessageKey.RFQ_ITEM_NOT_PURCHASABLE,
        )


class RfqNotFoundError(BusinessError):
    """40507 — 询价单不存在(含越权,不暴露存在性)。"""
    def __init__(self):
        super().__init__(
            status.HTTP_404_NOT_FOUND, 40507,
            "RFQ not found",
            message_key=MessageKey.RFQ_NOT_FOUND,
        )


class RfqStateInvalidError(BusinessError):
    """40508 — 非法状态转换。"""
    def __init__(self, current_status: str | None = None):
        msg = f"Invalid RFQ state transition from {current_status}" if current_status else "Invalid RFQ state transition"
        super().__init__(
            status.HTTP_409_CONFLICT, 40508,
            msg,
            message_key=MessageKey.RFQ_STATE_INVALID,
        )


class RfqDuplicateSkuError(BusinessError):
    """40509 — DIRECT 重复 SKU。保留兼容旧调用。"""
    def __init__(self):
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY, 40509,
            "Duplicate SKU in request items",
            message_key=MessageKey.RFQ_DUPLICATE_SKU,
        )


class RfqDuplicateItemError(BusinessError):
    """40509 — 询价行重复（同一商品+同一变体组合）。"""
    def __init__(self):
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY, 40509,
            "Duplicate product+variant combination in request items",
            message_key=MessageKey.RFQ_DUPLICATE_SKU,
        )


class RfqSourceNotAllowedError(BusinessError):
    """40514 — 运营仅限 DIRECT 来源,不允许其他来源类型。"""
    def __init__(self):
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY, 40514,
            "Source type not allowed for operator",
            message_key=MessageKey.RFQ_SOURCE_NOT_ALLOWED,
        )


class RfqNoGenerationFailedError(BusinessError):
    """40515 — rfq_no 生成重试耗尽。"""
    def __init__(self):
        super().__init__(
            status.HTTP_409_CONFLICT, 40515,
            "RFQ number generation failed after retries",
            message_key=MessageKey.RFQ_NO_GENERATION_FAILED,
        )


# ── 报价域 405xx(接 RFQ 40514)──────────────────────────────


class QuoteRfqStateInvalidError(BusinessError):
    """40510 — 报价操作时 RFQ 状态非法(或 accept 时无 ACTIVE 报价)。"""
    def __init__(self, current_status: str | None = None):
        msg = f"Quote operation not allowed: RFQ in {current_status}" if current_status else "Quote operation not allowed for current RFQ state"
        super().__init__(
            status.HTTP_409_CONFLICT, 40510,
            msg,
            message_key=MessageKey.QUOTE_RFQ_STATE_INVALID,
        )


class QuoteNotFoundError(BusinessError):
    """40511 — 报价不存在。"""
    def __init__(self):
        super().__init__(
            status.HTTP_404_NOT_FOUND, 40511,
            "Quote not found",
            message_key=MessageKey.QUOTE_NOT_FOUND,
        )


class QuoteItemMismatchError(BusinessError):
    """40512 — 报价行 rfq_item 不属本 RFQ / 重复。"""
    def __init__(self):
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY, 40512,
            "Quote item does not belong to this RFQ or is duplicated",
            message_key=MessageKey.QUOTE_ITEM_MISMATCH,
        )


class QuoteLinesIncompleteError(BusinessError):
    """40513 — 报价未覆盖全部 rfq_items。"""
    def __init__(self):
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY, 40513,
            "Quote does not cover all RFQ items",
            message_key=MessageKey.QUOTE_LINES_INCOMPLETE,
        )


class QuoteLineNoPriceError(BusinessError):
    """40514 — 非跳过行缺少 unit_price。"""
    def __init__(self):
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY, 40514,
            "Non-skipped quote line must have unit_price",
            message_key=MessageKey.QUOTE_LINE_NO_PRICE,
        )


class RfqAlreadyClaimedError(BusinessError):
    """40516 — 询价单已被其他运营受理。"""
    def __init__(self):
        super().__init__(
            status.HTTP_409_CONFLICT, 40516,
            "RFQ has already been claimed by another operator",
            message_key=MessageKey.RFQ_ALREADY_CLAIMED,
        )


class RfqItemNotFoundError(BusinessError):
    """40517 — 询价行项不存在或不属于本询价单。"""
    def __init__(self):
        super().__init__(
            status.HTTP_404_NOT_FOUND, 40517,
            "RFQ item not found",
            message_key=MessageKey.RFQ_ITEM_NOT_FOUND,
        )


class RfqNotAssignedToYouError(BusinessError):
    """40518 — 操作的询价单不是当前运营受理的。"""
    def __init__(self):
        super().__init__(
            status.HTTP_403_FORBIDDEN, 40518,
            "This RFQ is not assigned to you",
            message_key=MessageKey.RFQ_NOT_ASSIGNED_TO_YOU,
        )


class RfqMinOneItemError(BusinessError):
    """40519 — 询价单至少保留一个行项。"""
    def __init__(self):
        super().__init__(
            status.HTTP_400_BAD_REQUEST, 40519,
            "At least one item is required",
            message_key=MessageKey.RFQ_MIN_ONE_ITEM,
        )


class CartDuplicateVariantError(BusinessError):
    """40520 — 询价篮改变体后与篮中已有行规格重复。"""
    def __init__(self):
        super().__init__(
            status.HTTP_409_CONFLICT, 40520,
            "Variant combination already exists in cart",
            message_key=MessageKey.CART_DUPLICATE_VARIANT,
        )


# ── 附件域 405xx ──────────────────────────────────────────


class AttachmentTooManyError(BusinessError):
    """40521 — 关联附件数超上限(6)。"""
    def __init__(self):
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY, 40521,
            "Too many attachments, maximum 6 allowed",
            message_key=MessageKey.ATTACHMENT_TOO_MANY,
        )


class AttachmentTypeNotAllowedError(BusinessError):
    """40523 — 附件类型不允许(不落允许族)。"""
    def __init__(self):
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY, 40523,
            "Attachment type not allowed",
            message_key=MessageKey.ATTACHMENT_TYPE_NOT_ALLOWED,
        )


class AttachmentTooLargeError(BusinessError):
    """40524 — 附件超大。"""
    def __init__(self):
        super().__init__(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, 40524,
            "Attachment too large",
            message_key=MessageKey.ATTACHMENT_TOO_LARGE,
        )


class AttachmentNotFoundError(BusinessError):
    """40525 — 附件不存在/无权/孤儿失效(不暴露存在性)。"""
    def __init__(self):
        super().__init__(
            status.HTTP_404_NOT_FOUND, 40525,
            "Attachment not found",
            message_key=MessageKey.ATTACHMENT_NOT_FOUND,
        )


class AttachmentAlreadyLinkedError(BusinessError):
    """40526 — 附件已归属其他对象。"""
    def __init__(self):
        super().__init__(
            status.HTTP_409_CONFLICT, 40526,
            "Attachment already linked to another object",
            message_key=MessageKey.ATTACHMENT_ALREADY_LINKED,
        )


class AttachmentOrphanQuotaError(BusinessError):
    """40528 — 孤儿附件配额超限。"""
    def __init__(self):
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY, 40528,
            "Orphan attachment quota exceeded",
            message_key=MessageKey.ATTACHMENT_ORPHAN_QUOTA,
        )


class RfqNoQuoteToExportError(BusinessError):
    """40527 — 该 RFQ 无 ACTIVE 报价,无可导出单据。"""
    def __init__(self):
        super().__init__(
            status.HTTP_409_CONFLICT, 40527,
            "No active quote available for export",
            message_key=MessageKey.RFQ_NO_QUOTE_TO_EXPORT,
        )


class RfqItemsOrRemarkRequiredError(BusinessError):
    """40529 — 询价单必须至少有行项或需求说明。"""
    def __init__(self):
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY, 40529,
            "Either items or remark is required",
            message_key=MessageKey.RFQ_ITEMS_OR_REMARK_REQUIRED,
        )


def success(data: Any = None, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data}