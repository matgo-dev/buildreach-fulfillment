"""业务异常 + 统一响应格式。

业务码(body.code)与 HTTP status 解耦,仅承载业务语义。

格式 5 位:C MM SS
- C : 4=客户端类, 5=服务端类
- MM: 模块段
- SS: 模块内顺序号(01–99)

模块段位(M0 基座只落地通用与鉴权;后续段随增量落):
  MM | 模块       | 现有码
  00 | 通用与鉴权 | 40001–40010
  12 | 商品生命周期 | 412xx
  13 | SKU 规格   | 413xx
  14 | 报价       | 414xx
  15 | 供应商     | 415xx
  16 | 采购单     | 416xx
  17 | 入库/应付  | 417xx(含 41710 撤销入库穿仓守卫)
  18 | 销售单     | 418xx
  19 | 出库单     | 419xx(含 41910 撤销出库·柜已装柜/发运守卫)
  20 | 柜/发运    | 420xx(42002 非法转移·单义;42003/42004 装柜守卫;42005 字段门禁;42006 编辑冲突)

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


class AccountLockedError(BusinessError):
    """账号级登录锁定(users.locked_until 未过期)。

    与 40002(进程内限流,identifier+ip 维度)不同,本错误来自落库的账号锁,换 IP/重启不绕过。
    提示会暴露「账号存在」—— 公网下锁定可用性(用户须知道为何登不上、找管理员解锁)
    与防枚举的权衡,取前者。
    """

    def __init__(self, message: str = "账号已锁定,请稍后重试或联系管理员"):
        super().__init__(status.HTTP_429_TOO_MANY_REQUESTS, 40010, message,
                         message_key=MessageKey.ACCOUNT_LOCKED)


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


class QuotationLineReferencedBySalesOrderError(BusinessError):
    """报价行被(任意状态)销售单行引用,不可删行/删单——单据流溯源(FK RESTRICT)的干净前置,
    防裸 IntegrityError 500。改数量/价格不触 FK,不走此错。"""

    def __init__(self, message: str = "Quotation line is referenced by a sales order"):
        super().__init__(status.HTTP_409_CONFLICT, 41411, message,
                         message_key=MessageKey.QUOTATION_LINE_REFERENCED)


class QuotationCannotConvertError(BusinessError):
    """只有锁档态(LOCKED)报价可转销售单;其它态(草稿/已转/已作废)一律拒。"""

    def __init__(self, message: str = "Only a locked quotation can be converted to a sales order"):
        super().__init__(status.HTTP_409_CONFLICT, 41409, message,
                         message_key=MessageKey.QUOTATION_CANNOT_CONVERT)


class QuotationCustomerInactiveError(BusinessError):
    """报价指派停用客户(新建或换客户)。存量单据的客户后停用不受此拦(只拦新指派)。"""

    def __init__(self, message: str = "客户已停用,不可用于新报价"):
        super().__init__(status.HTTP_409_CONFLICT, 41410, message)


class QuotationDuplicateSkuError(BusinessError):
    """报价单/销售单同一 SKU 重复行(上游守卫,契约 §0-11 / §1):一 SKU 一价,
    结构性禁重复(DB UNIQUE 兜底,service 前置拒绝)。业务公理:无阶梯价/同 SKU 多价。"""

    def __init__(self, message: str = "Duplicate SKU line in quotation or sales order"):
        super().__init__(status.HTTP_409_CONFLICT, 41412, message)


# 模块段 15 = 供应商(供应商主数据)。见 db/models/supplier.py SupplierStatus。
class SupplierNotFoundError(BusinessError):
    def __init__(self, message: str = "Supplier not found"):
        super().__init__(status.HTTP_404_NOT_FOUND, 41501, message,
                         message_key=MessageKey.SUPPLIER_NOT_FOUND)


class SupplierCodeConflictError(BusinessError):
    """code 冲突(理论走发号不冲突,兜底)。"""

    def __init__(self, message: str = "Supplier code conflict"):
        super().__init__(status.HTTP_409_CONFLICT, 41502, message,
                         message_key=MessageKey.SUPPLIER_CODE_CONFLICT)


class SupplierInactiveError(BusinessError):
    """停用态供应商不可被新 PO 选用(供应商域自身报错)。"""

    def __init__(self, message: str = "Supplier is inactive"):
        super().__init__(status.HTTP_409_CONFLICT, 41503, message,
                         message_key=MessageKey.SUPPLIER_INACTIVE)


# 模块段 16 = 采购单(采购单状态机 + 建单/整单对账)。见 db/models/purchase_order.py。
class PurchaseOrderNotFoundError(BusinessError):
    def __init__(self, message: str = "Purchase order not found"):
        super().__init__(status.HTTP_404_NOT_FOUND, 41601, message,
                         message_key=MessageKey.PURCHASE_ORDER_NOT_FOUND)


class PurchaseOrderInvalidTransitionError(BusinessError):
    """状态转移不在 PURCHASE_ORDER_TRANSITIONS 矩阵。"""

    def __init__(self, message: str = "Illegal purchase order status transition"):
        super().__init__(status.HTTP_409_CONFLICT, 41602, message,
                         message_key=MessageKey.PURCHASE_ORDER_INVALID_TRANSITION)


class PurchaseOverQuotaError(BusinessError):
    """超采:累计(非取消 PO 行,含草稿)> 对应 SO 行数量。"""

    def __init__(self, message: str = "Purchase quantity exceeds sales order line remaining"):
        super().__init__(status.HTTP_409_CONFLICT, 41603, message,
                         message_key=MessageKey.PURCHASE_ORDER_OVER_PURCHASE)


class PurchaseSourceSalesOrderInvalidError(BusinessError):
    """源 SO 无效:不存在或非 CONFIRMED(采购须基于已确认销售单发起)。"""

    def __init__(self, message: str = "Source sales order not found or not confirmed"):
        super().__init__(status.HTTP_404_NOT_FOUND, 41604, message,
                         message_key=MessageKey.PURCHASE_ORDER_SOURCE_INVALID)


class PurchaseOrderEditConflictError(BusinessError):
    """乐观锁:expected_updated_at 与库中不一致(或引用了不存在的行 id)。"""

    def __init__(self, message: str = "Purchase order was modified by someone else"):
        super().__init__(status.HTTP_409_CONFLICT, 41605, message,
                         message_key=MessageKey.PURCHASE_ORDER_EDIT_CONFLICT)


class PurchaseOrderSupplierInactiveError(BusinessError):
    """建 PO 选用的供应商为停用态。"""

    def __init__(self, message: str = "Cannot create purchase order for an inactive supplier"):
        super().__init__(status.HTTP_409_CONFLICT, 41606, message,
                         message_key=MessageKey.PURCHASE_ORDER_SUPPLIER_INACTIVE)


class PurchaseOrderNotDraftError(BusinessError):
    """对非 DRAFT 采购单执行编辑 / 硬删。"""

    def __init__(self, message: str = "Purchase order is not a draft"):
        super().__init__(status.HTTP_409_CONFLICT, 41607, message,
                         message_key=MessageKey.PURCHASE_ORDER_NOT_DRAFT)


class PurchaseOrderEmptyError(BusinessError):
    """空采购单(无行):建单 / 编辑对账后 / 确认前均杜绝。"""

    def __init__(self, message: str = "Purchase order must have at least one line"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 41608, message,
                         message_key=MessageKey.PURCHASE_ORDER_EMPTY)


class PurchaseOrderHasActiveInboundError(BusinessError):
    """CONFIRMED→CANCELLED 被拦:存在活动入库单({IN_TRANSIT, RECEIVED})。
    货已在途/已收,订货承诺不可单方作废(契约 D5)。"""

    def __init__(self, message: str = "Cannot cancel a purchase order with active inbound orders"):
        super().__init__(status.HTTP_409_CONFLICT, 41609, message,
                         message_key=MessageKey.PURCHASE_ORDER_HAS_ACTIVE_INBOUND)


# 模块段 17 = 入库单 / 应付款。见 db/models/inbound_order.py、db/models/payable.py。
class InboundOrderNotFoundError(BusinessError):
    def __init__(self, message: str = "Inbound order not found"):
        super().__init__(status.HTTP_404_NOT_FOUND, 41701, message,
                         message_key=MessageKey.INBOUND_ORDER_NOT_FOUND)


class InboundSourcePurchaseOrderInvalidError(BusinessError):
    """源 PO 无效:不存在或非 CONFIRMED(入库须基于已确认采购单登记)。"""

    def __init__(self, message: str = "Source purchase order not found or not confirmed"):
        super().__init__(status.HTTP_409_CONFLICT, 41702, message,
                         message_key=MessageKey.INBOUND_ORDER_SOURCE_PO_INVALID)


class InboundOverReceiptError(BusinessError):
    """超收:累计(非取消入库行,含在途)> 对应 PO 行数量。"""

    def __init__(self, message: str = "Inbound quantity exceeds purchase order line remaining"):
        super().__init__(status.HTTP_409_CONFLICT, 41703, message,
                         message_key=MessageKey.INBOUND_ORDER_OVER_RECEIPT)


class InboundOrderInvalidTransitionError(BusinessError):
    """状态转移不在 INBOUND_ORDER_TRANSITIONS 矩阵。"""

    def __init__(self, message: str = "Illegal inbound order status transition"):
        super().__init__(status.HTTP_409_CONFLICT, 41704, message,
                         message_key=MessageKey.INBOUND_ORDER_INVALID_TRANSITION)


class InboundOrderNotInTransitError(BusinessError):
    """对非 IN_TRANSIT 入库单执行编辑(整单保存仅在途)。"""

    def __init__(self, message: str = "Inbound order is not in transit"):
        super().__init__(status.HTTP_409_CONFLICT, 41705, message,
                         message_key=MessageKey.INBOUND_ORDER_NOT_IN_TRANSIT)


class InboundLineNotInPurchaseOrderError(BusinessError):
    """入库行引用的 PO 行不属于该采购单。"""

    def __init__(self, message: str = "Inbound line references a purchase order line not on this PO"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 41706, message,
                         message_key=MessageKey.INBOUND_ORDER_LINE_NOT_IN_PO)


class InboundOrderEmptyError(BusinessError):
    """空入库单(无行):建单 / 编辑对账后均杜绝。"""

    def __init__(self, message: str = "Inbound order must have at least one line"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 41707, message,
                         message_key=MessageKey.INBOUND_ORDER_EMPTY)


class PayableAllocatedCannotUnreceiveError(BusinessError):
    """撤销入库被拦:对应 payable 已有核销(amount_allocated > 0),不可撤销。"""

    def __init__(self, message: str = "Cannot unreceive: payable has been partially allocated"):
        super().__init__(status.HTTP_409_CONFLICT, 41708, message,
                         message_key=MessageKey.PAYABLE_ALLOCATED_CANNOT_UNRECEIVE)


class InboundOrderEditConflictError(BusinessError):
    """乐观锁:expected_updated_at 与库中不一致(整单保存被并发修改抢先)。"""

    def __init__(self, message: str = "Inbound order was modified by someone else"):
        super().__init__(status.HTTP_409_CONFLICT, 41709, message,
                         message_key=MessageKey.INBOUND_ORDER_EDIT_CONFLICT)


class InboundUnreceiveWouldGoNegativeError(BusinessError):
    """撤销入库被拦:货已被出库消费,撤回将使某 (SO, SKU) 可发穿仓(available < 0)。
    须先撤销相关出库单再撤销入库(库存契约收紧型写入口守卫)。
    biz_data 带逐 (so,sku) 明细(销售单号/品名/穿仓后可发),镜像 41902 的明细形状。"""

    def __init__(self, message: str = "Cannot unreceive: stock has been outbound, revert outbound first",
                 data: Any = None):
        super().__init__(status.HTTP_409_CONFLICT, 41710, message, data=data)


class InboundDuplicateLineError(BusinessError):
    """入库单 payload 同一 PO 行重复出现(一 PO 行一入库行,DB UNIQUE(inb, po_line) 兜底,
    service 前置拒绝——否则打穿到约束成 500)。"""

    def __init__(self, message: str = "Duplicate purchase order line in inbound payload"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 41711, message)


# 模块段 18 = 销售单(SO 状态机)。见 db/models/sales_order.py SalesOrderStatus。
class SalesOrderInvalidTransitionError(BusinessError):
    """状态转移不在 SALES_ORDER_TRANSITIONS 矩阵(重复取消等)。"""

    def __init__(self, message: str = "Illegal sales order status transition"):
        super().__init__(status.HTTP_409_CONFLICT, 41801, message,
                         message_key=MessageKey.SALES_ORDER_INVALID_TRANSITION)


class SalesOrderHasActivePurchaseError(BusinessError):
    """取消被拦:存在非 CANCELLED 的采购单(镜像 41609,方向相反)。
    不级联砍下游——解链人工自下而上:先取消全部 PO 再取消 SO。"""

    def __init__(self, message: str = "Cannot cancel a sales order with active purchase orders"):
        super().__init__(status.HTTP_409_CONFLICT, 41802, message,
                         message_key=MessageKey.SALES_ORDER_HAS_ACTIVE_PURCHASE)


class SalesOrderHasActiveOutboundError(BusinessError):
    """取消被拦:存在非 CANCELLED 的出库单(镜像 41802,下游轴从采购扩到出库)。
    不级联砍下游——解链人工自下而上:先取消/撤销全部出库单再取消 SO。"""

    def __init__(self, message: str = "Cannot cancel a sales order with active outbound orders"):
        super().__init__(status.HTTP_409_CONFLICT, 41803, message)


# 模块段 19 = 出库单(出库单状态机 + 确认装柜可发闸)。见 db/models/outbound_order.py。
class OutboundOrderInvalidTransitionError(BusinessError):
    """状态转移不在 OUTBOUND_ORDER_TRANSITIONS 矩阵。"""

    def __init__(self, message: str = "Illegal outbound order status transition"):
        super().__init__(status.HTTP_409_CONFLICT, 41901, message)


class OutboundInsufficientAvailableError(BusinessError):
    """确认装柜被拦:某 (SO, SKU) 本单需发量 > 可发(available = Σ入库 − Σ出库)。
    biz_data 带逐 sku 明细(可发/需发)。"""

    def __init__(self, message: str = "Insufficient available stock to issue outbound", data: Any = None):
        super().__init__(status.HTTP_409_CONFLICT, 41902, message, data=data)


class OutboundLineNotInSalesOrderError(BusinessError):
    """出库行引用的 SO 行不属于该出库单头上的 SO,或行 sku 与 SO 行不一致。"""

    def __init__(self, message: str = "Outbound line references a sales order line not on this SO"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 41903, message)


class OutboundActiveOrderExistsError(BusinessError):
    """同柜同来源 SO 已存在活动出库单(偏唯一 uq_oborders_shipment_so_active 兜底,service 前置拒绝)。"""

    def __init__(self, message: str = "An active outbound order already exists for this shipment and sales order"):
        super().__init__(status.HTTP_409_CONFLICT, 41904, message)


class OutboundSalesOrderNotConfirmedError(BusinessError):
    """出库须锚定 CONFIRMED 销售单(取消/其它态一律拒)。"""

    def __init__(self, message: str = "Outbound requires a confirmed sales order"):
        super().__init__(status.HTTP_409_CONFLICT, 41905, message)


class OutboundShipmentNotOpenError(BusinessError):
    """装柜须柜为 OPEN(已取消柜不可再装)。"""

    def __init__(self, message: str = "Outbound requires an open shipment"):
        super().__init__(status.HTTP_409_CONFLICT, 41906, message)


class ReceivableAllocatedCannotRevertError(BusinessError):
    """撤销出库被拦:对应 receivable 已有核销(amount_allocated > 0),不可撤销(镜像 41708)。"""

    def __init__(self, message: str = "Cannot revert outbound: receivable has been partially allocated"):
        super().__init__(status.HTTP_409_CONFLICT, 41907, message)


class OutboundOrderEditConflictError(BusinessError):
    """乐观锁:expected_updated_at 与库中不一致(草稿被他人改后 stale 提交)。镜像 41605/41411。
    与 41901(非法转移/非草稿编辑)分开,前端据此提示「已被他人修改,请刷新」而非「状态非法」。"""

    def __init__(self, message: str = "Outbound order was modified by someone else"):
        super().__init__(status.HTTP_409_CONFLICT, 41908, message)


class OutboundDuplicateLineError(BusinessError):
    """出库单 payload 同一 SO 行重复出现(一 SO 行一出库行,DB UNIQUE(ob, so_line) 兜底,
    service 前置拒绝——否则打穿到约束成 500。镜像 41711)。"""

    def __init__(self, message: str = "Duplicate sales order line in outbound payload"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 41909, message)


class OutboundShipmentLoadedCannotRevertError(BusinessError):
    """撤销出库被拦:柜已装柜/发运(status ≠ OPEN)——封柜后柜内出库单冻结,须先撤装柜
    (发运侧 LOADED→OPEN)再撤出库(兑现出库契约预留守卫;守卫在锁序末尾锁柜头 FOR UPDATE)。"""

    def __init__(self, message: str = "Cannot revert outbound: shipment already loaded or departed"):
        super().__init__(status.HTTP_409_CONFLICT, 41910, message)


# 模块段 20 = 柜 / 发运(发运单状态机 + 船务字段编辑门禁)。见 db/models/shipment_order.py。
class ShipmentHasActiveOutboundError(BusinessError):
    """取消柜被拦:柜下存在非 CANCELLED 出库单。先取消柜内出库单再取消柜。"""

    def __init__(self, message: str = "Cannot cancel a shipment with active outbound orders"):
        super().__init__(status.HTTP_409_CONFLICT, 42001, message)


class ShipmentInvalidTransitionError(BusinessError):
    """状态转移不在 SHIPMENT_ORDER_TRANSITIONS 矩阵(单义:仅非法转移)。
    编辑字段门禁分到 42005、编辑冲突分到 42006,不并入本码。"""

    def __init__(self, message: str = "Illegal shipment status transition"):
        super().__init__(status.HTTP_409_CONFLICT, 42002, message)


class ShipmentHasDraftOutboundError(BusinessError):
    """装柜确认被拦:柜内存在草稿(DRAFT)出库单——只有已确认(已扣库存)的出库单代表真实
    装柜,草稿只是意图。biz_data 带草稿单号列表({"draft_nos": [...]})。"""

    def __init__(self, message: str = "Cannot load: shipment has draft outbound orders",
                 data: Any = None):
        super().__init__(status.HTTP_409_CONFLICT, 42003, message, data=data)


class ShipmentEmptyCannotLoadError(BusinessError):
    """装柜确认被拦:空柜(无任何非 CANCELLED 出库单)不可装柜。"""

    def __init__(self, message: str = "Cannot load an empty shipment"):
        super().__init__(status.HTTP_409_CONFLICT, 42004, message)


class ShipmentFieldNotEditableError(BusinessError):
    """编辑门禁:提交值 ≠ 库中值,且该字段 ∉ 当前状态可编辑集(diff 式门禁,
    SHIPMENT_EDITABLE_FIELDS_BY_STATUS 单一源头)。biz_data 带被拒字段名({"fields": [...]})。
    与 42002(非法转移)分码:是两种用户情境(镜像出库 41901/41908 分码先例)。"""

    def __init__(self, message: str = "Field not editable in current shipment status",
                 data: Any = None):
        super().__init__(status.HTTP_400_BAD_REQUEST, 42005, message, data=data)


class ShipmentEditConflictError(BusinessError):
    """乐观锁:expected_updated_at 与库中不一致(柜被他人改后 stale 提交)。镜像 41908,
    前端据此提示「已被他人修改,请刷新」而非「状态非法」。"""

    def __init__(self, message: str = "Shipment was modified by someone else"):
        super().__init__(status.HTTP_409_CONFLICT, 42006, message)


def success(data: Any = None, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data}
