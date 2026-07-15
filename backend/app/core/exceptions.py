"""业务异常 + 统一响应格式。

业务码(body.code)与 HTTP status 解耦,仅承载业务语义。

格式 5 位:C MM SS
- C : 4=客户端类, 5=服务端类
- MM: 模块段
- SS: 模块内顺序号(01–99)

模块段位(M0 基座只落地通用与鉴权):
  MM | 模块       | 现有码
  00 | 通用与鉴权 | 40001–40009

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


class NotFoundError(BusinessError):
    def __init__(self, message: str = "Not found"):
        super().__init__(status.HTTP_404_NOT_FOUND, 40008, message, message_key=MessageKey.NOT_FOUND)


class SpecContractError(BusinessError):
    """spec_jsonb 契约违规(key 唯一/来自模板/zh 必填/禁空串等)。模块段 13=SKU。"""

    def __init__(self, message: str = "spec_jsonb contract violated"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 41301, message,
                         message_key=MessageKey.SPEC_CONTRACT)


# 模块段 12 = 商品生命周期(SPU 状态机)。见 db/models/spu.py SpuStatus。
class ProductNotEditableError(BusinessError):
    """商品当前状态不在 EDITABLE 集(ACTIVE 已启用),需先停用再改/删。"""

    def __init__(self, message: str = "Product not editable in current status"):
        super().__init__(status.HTTP_409_CONFLICT, 41201, message,
                         message_key=MessageKey.PRODUCT_NOT_EDITABLE)


class IllegalStatusTransitionError(BusinessError):
    """状态转移不在 TRANSITIONS 白名单(如 DRAFT→INACTIVE、ACTIVE→DRAFT)。"""

    def __init__(self, message: str = "Illegal status transition"):
        super().__init__(status.HTTP_409_CONFLICT, 41202, message,
                         message_key=MessageKey.PRODUCT_ILLEGAL_TRANSITION)


class ProductIncompleteError(BusinessError):
    """启用(→ACTIVE)完备性未达标:至少需一个在售 SKU(不卡参考价,见 has_active_sku)。"""

    def __init__(self, message: str = "Product incomplete for activation"):
        super().__init__(status.HTTP_409_CONFLICT, 41203, message,
                         message_key=MessageKey.PRODUCT_INCOMPLETE)


# 模块段 14 = 报价(报价单状态机 + 整单保存)。见 db/models/quotation.py QuotationStatus。
class QuotationNotDraftError(BusinessError):
    """对非 DRAFT 报价单执行改/删/整单保存。"""

    def __init__(self, message: str = "Quotation is not a draft"):
        super().__init__(status.HTTP_409_CONFLICT, 41401, message,
                         message_key=MessageKey.QUOTATION_NOT_DRAFT)


class QuotationEmptyLinesError(BusinessError):
    """锁档要求至少一行。"""

    def __init__(self, message: str = "Quotation has no lines to lock"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 41402, message,
                         message_key=MessageKey.QUOTATION_EMPTY_LINES)


class QuotationInvalidTransitionError(BusinessError):
    """状态转移不在 QUOTATION_TRANSITIONS 矩阵。"""

    def __init__(self, message: str = "Illegal quotation status transition"):
        super().__init__(status.HTTP_409_CONFLICT, 41403, message,
                         message_key=MessageKey.QUOTATION_INVALID_TRANSITION)


class QuotationCannotUnlockConvertedError(BusinessError):
    """已转销售的报价不可解锁。"""

    def __init__(self, message: str = "Cannot unlock a converted quotation"):
        super().__init__(status.HTTP_409_CONFLICT, 41404, message,
                         message_key=MessageKey.QUOTATION_CANNOT_UNLOCK_CONVERTED)


class QuotationEditConflictError(BusinessError):
    """乐观锁:expected_updated_at 与库中不一致(或引用了不存在的行 id)。"""

    def __init__(self, message: str = "Quotation was modified by someone else"):
        super().__init__(status.HTTP_409_CONFLICT, 41405, message,
                         message_key=MessageKey.QUOTATION_EDIT_CONFLICT)


class QuotationInvalidLineError(BusinessError):
    """行引用的 SKU 不存在或不可报价(SKU/SPU 非 ACTIVE)。"""

    def __init__(self, message: str = "Quotation line references a non-quotable SKU"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 41406, message,
                         message_key=MessageKey.QUOTATION_INVALID_LINE)


class QuotationCannotVoidError(BusinessError):
    """当前状态不可作废(仅 DRAFT/LOCKED 可作废;CONVERTED 终态、VOID 已作废)。"""

    def __init__(self, message: str = "Cannot void a quotation in its current status"):
        super().__init__(status.HTTP_409_CONFLICT, 41407, message,
                         message_key=MessageKey.QUOTATION_CANNOT_VOID)


class QuotationInvalidSalespersonError(BusinessError):
    """报价人非法:须 ACTIVE 且持 quote:manage(同 /users/selectable 口径,写入口硬挡)。"""

    def __init__(self, message: str = "Salesperson must be an active quote-capable user"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 41408, message,
                         message_key=MessageKey.QUOTATION_INVALID_SALESPERSON)


def success(data: Any = None, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data}
