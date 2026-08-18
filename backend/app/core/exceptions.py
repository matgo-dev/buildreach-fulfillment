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
  17 | 入库/应付  | 417xx(含 41710 撤销入库穿仓守卫;41712 入库财务边界;
       |            |       41713–41717 采购退货/供应商贷项单)
  18 | 销售单     | 418xx
  19 | 出库单     | 419xx
  20 | 柜/发运    | 420xx(42002 非法转移·单义;42003/42004 封柜守卫;42005 字段门禁;42006 编辑冲突;
       |            |       42007 撤离港带活动事件;42008 非 DEPARTED 不可录事件;42009 重复到港;42010 事件越柜;
       |            |       42011 撤封柜带活动报关;42012 柜态不可报关;42013 重复活动报关;42014 报关越柜;42015 报关编辑冲突;
       |            |       42016 报关单号已被占用)
  21 | 附件       | 421xx(42101 类型不允许;42102 超大;42103 孤儿配额;42104 不可用;42105 数量超上限)
  22 | 财务       | 422xx(核销引擎:42201 核销超收付款未分配;42202 核销超账未结金额;42203 跨币种;
       |            |       42204 客户/供应商不匹配;42205 反核销记录不存在/已反核销;42206 账已作废不可核销;
       |            |       42207 认领非 UNCLAIMED;42208 已有活动核销不可作废;42209 收付款单已作废不可操作;
       |            |       42210 同对已有活动核销,先反核销再重核)

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


class BusinessError(HTTPException):
    """所有业务异常的基类。"""

    def __init__(
        self,
        http_status: int,
        biz_code: int,
        message: str,
        data: Any = None,
    ):
        super().__init__(status_code=http_status, detail=message)
        self.biz_code = biz_code
        self.biz_message = message
        self.biz_data = data


class InvalidCredentialsError(BusinessError):
    def __init__(self, message: str = "Invalid credentials"):
        super().__init__(status.HTTP_401_UNAUTHORIZED, 40001, message)


class TooManyAttemptsError(BusinessError):
    def __init__(self, message: str = "Too many failed attempts, account locked"):
        super().__init__(status.HTTP_429_TOO_MANY_REQUESTS, 40002, message)


class PermissionDeniedError(BusinessError):
    def __init__(self, message: str = "Permission denied"):
        super().__init__(status.HTTP_403_FORBIDDEN, 40003, message)


class NotAuthenticatedError(BusinessError):
    def __init__(self, message: str = "Not authenticated"):
        super().__init__(status.HTTP_401_UNAUTHORIZED, 40004, message)


class AccountDisabledError(BusinessError):
    def __init__(self, message: str = "Account disabled"):
        super().__init__(status.HTTP_403_FORBIDDEN, 40005, message)


class AccountDeactivatedError(BusinessError):
    def __init__(self, message: str = "Account has been deactivated"):
        super().__init__(status.HTTP_403_FORBIDDEN, 40305, message)


class ValidationFailedError(BusinessError):
    def __init__(self, message: str = "Validation failed"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 40006, message)


class PasswordChangeRequiredError(BusinessError):
    """must_change_password=True 的账号访问非豁免端点时抛出。"""

    def __init__(self, message: str = "Password change required"):
        super().__init__(status.HTTP_403_FORBIDDEN, 40007, message)


class ConflictError(BusinessError):
    def __init__(self, message: str = "Resource conflict"):
        super().__init__(status.HTTP_409_CONFLICT, 40009, message)


class AccountLockedError(BusinessError):
    """账号级登录锁定(users.locked_until 未过期)。

    与 40002(进程内限流,identifier+ip 维度)不同,本错误来自落库的账号锁,换 IP/重启不绕过。
    提示会暴露「账号存在」—— 公网下锁定可用性(用户须知道为何登不上、找管理员解锁)
    与防枚举的权衡,取前者。
    """

    def __init__(self, message: str = "账号已锁定,请稍后重试或联系管理员"):
        super().__init__(status.HTTP_429_TOO_MANY_REQUESTS, 40010, message)


class NotFoundError(BusinessError):
    def __init__(self, message: str = "Not found"):
        super().__init__(status.HTTP_404_NOT_FOUND, 40008, message)


class SpecContractError(BusinessError):
    """spec_jsonb 契约违规(key 唯一/来自模板/zh 必填/禁空串等)。模块段 13=SKU。"""

    def __init__(self, message: str = "spec_jsonb contract violated"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 41301, message)


# 模块段 12 = 商品生命周期(SPU 状态机)。见 db/models/spu.py SpuStatus。
class ProductNotEditableError(BusinessError):
    """商品当前状态不在 EDITABLE 集(ACTIVE 已启用),需先停用再改/删。"""

    def __init__(self, message: str = "Product not editable in current status"):
        super().__init__(status.HTTP_409_CONFLICT, 41201, message)


class IllegalStatusTransitionError(BusinessError):
    """状态转移不在 TRANSITIONS 白名单(如 DRAFT→INACTIVE、ACTIVE→DRAFT)。"""

    def __init__(self, message: str = "Illegal status transition"):
        super().__init__(status.HTTP_409_CONFLICT, 41202, message)


class ProductIncompleteError(BusinessError):
    """启用(→ACTIVE)完备性未达标:至少需一个在售 SKU(不卡参考价,见 has_active_sku)。"""

    def __init__(self, message: str = "Product incomplete for activation"):
        super().__init__(status.HTTP_409_CONFLICT, 41203, message)


# 模块段 14 = 报价(报价单状态机 + 整单保存)。见 db/models/quotation.py QuotationStatus。
class QuotationNotDraftError(BusinessError):
    """对非 DRAFT 报价单执行改/删/整单保存。"""

    def __init__(self, message: str = "Quotation is not a draft"):
        super().__init__(status.HTTP_409_CONFLICT, 41401, message)


class QuotationEmptyLinesError(BusinessError):
    """锁档要求至少一行。"""

    def __init__(self, message: str = "Quotation has no lines to lock"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 41402, message)


class QuotationInvalidTransitionError(BusinessError):
    """状态转移不在 QUOTATION_TRANSITIONS 矩阵。"""

    def __init__(self, message: str = "Illegal quotation status transition"):
        super().__init__(status.HTTP_409_CONFLICT, 41403, message)


class QuotationCannotUnlockConvertedError(BusinessError):
    """已转销售的报价不可解锁。"""

    def __init__(self, message: str = "Cannot unlock a converted quotation"):
        super().__init__(status.HTTP_409_CONFLICT, 41404, message)


class QuotationEditConflictError(BusinessError):
    """乐观锁:expected_updated_at 与库中不一致(或引用了不存在的行 id)。"""

    def __init__(self, message: str = "Quotation was modified by someone else"):
        super().__init__(status.HTTP_409_CONFLICT, 41405, message)


class QuotationInvalidLineError(BusinessError):
    """行引用的 SKU 不存在或不可报价(SKU/SPU 非 ACTIVE)。"""

    def __init__(self, message: str = "Quotation line references a non-quotable SKU"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 41406, message)


class QuotationCannotVoidError(BusinessError):
    """当前状态不可作废(仅 DRAFT/LOCKED 可作废;CONVERTED 终态、VOID 已作废)。"""

    def __init__(self, message: str = "Cannot void a quotation in its current status"):
        super().__init__(status.HTTP_409_CONFLICT, 41407, message)


class QuotationInvalidSalespersonError(BusinessError):
    """报价人非法:须 ACTIVE 且持 quote:manage(同 /users/selectable 口径,写入口硬挡)。"""

    def __init__(self, message: str = "Salesperson must be an active quote-capable user"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 41408, message)


class QuotationLineReferencedBySalesOrderError(BusinessError):
    """报价行被(任意状态)销售单行引用,不可删行/删单——单据流溯源(FK RESTRICT)的干净前置,
    防裸 IntegrityError 500。改数量/价格不触 FK,不走此错。"""

    def __init__(self, message: str = "Quotation line is referenced by a sales order"):
        super().__init__(status.HTTP_409_CONFLICT, 41411, message)


class QuotationCannotConvertError(BusinessError):
    """只有锁档态(LOCKED)报价可转销售单;其它态(草稿/已转/已作废)一律拒。"""

    def __init__(self, message: str = "Only a locked quotation can be converted to a sales order"):
        super().__init__(status.HTTP_409_CONFLICT, 41409, message)


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
        super().__init__(status.HTTP_404_NOT_FOUND, 41501, message)


class SupplierCodeConflictError(BusinessError):
    """code 冲突(理论走发号不冲突,兜底)。"""

    def __init__(self, message: str = "Supplier code conflict"):
        super().__init__(status.HTTP_409_CONFLICT, 41502, message)


class SupplierInactiveError(BusinessError):
    """停用态供应商不可被新 PO 选用(供应商域自身报错)。"""

    def __init__(self, message: str = "Supplier is inactive"):
        super().__init__(status.HTTP_409_CONFLICT, 41503, message)


# 模块段 16 = 采购单(采购单状态机 + 建单/整单对账)。见 db/models/purchase_order.py。
class PurchaseOrderNotFoundError(BusinessError):
    def __init__(self, message: str = "Purchase order not found"):
        super().__init__(status.HTTP_404_NOT_FOUND, 41601, message)


class PurchaseOrderInvalidTransitionError(BusinessError):
    """状态转移不在 PURCHASE_ORDER_TRANSITIONS 矩阵。"""

    def __init__(self, message: str = "Illegal purchase order status transition"):
        super().__init__(status.HTTP_409_CONFLICT, 41602, message)


class PurchaseOverQuotaError(BusinessError):
    """超采:累计(非取消 PO 行,含草稿)> 对应 SO 行数量。"""

    def __init__(self, message: str = "Purchase quantity exceeds sales order line remaining"):
        super().__init__(status.HTTP_409_CONFLICT, 41603, message)


class PurchaseSourceSalesOrderInvalidError(BusinessError):
    """源 SO 无效:不存在或非 CONFIRMED(采购须基于已确认销售单发起)。"""

    def __init__(self, message: str = "Source sales order not found or not confirmed"):
        super().__init__(status.HTTP_404_NOT_FOUND, 41604, message)


class PurchaseOrderEditConflictError(BusinessError):
    """乐观锁:expected_updated_at 与库中不一致(或引用了不存在的行 id)。"""

    def __init__(self, message: str = "Purchase order was modified by someone else"):
        super().__init__(status.HTTP_409_CONFLICT, 41605, message)


class PurchaseOrderSupplierInactiveError(BusinessError):
    """建 PO 选用的供应商为停用态。"""

    def __init__(self, message: str = "Cannot create purchase order for an inactive supplier"):
        super().__init__(status.HTTP_409_CONFLICT, 41606, message)


class PurchaseOrderNotDraftError(BusinessError):
    """对非 DRAFT 采购单执行编辑 / 硬删。"""

    def __init__(self, message: str = "Purchase order is not a draft"):
        super().__init__(status.HTTP_409_CONFLICT, 41607, message)


class PurchaseOrderEmptyError(BusinessError):
    """空采购单(无行):建单 / 编辑对账后 / 确认前均杜绝。"""

    def __init__(self, message: str = "Purchase order must have at least one line"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 41608, message)


class PurchaseOrderHasActiveInboundError(BusinessError):
    """CONFIRMED→CANCELLED 被拦:存在活动入库单({IN_TRANSIT, RECEIVED})。
    货已在途/已收,订货承诺不可单方作废(契约 D5)。"""

    def __init__(self, message: str = "Cannot cancel a purchase order with active inbound orders"):
        super().__init__(status.HTTP_409_CONFLICT, 41609, message)


class PurchaseOrderDuplicateLineError(BusinessError):
    """采购单 payload 同一 SO 行重复出现(一 SO 行一采购行,DB UNIQUE(po, so_line) 兜底,
    service 前置拒绝——否则打穿到约束成 500。镜像出/入库 41909/41711)。"""

    def __init__(self, message: str = "Duplicate sales order line in purchase order payload"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 41610, message)


# 模块段 17 = 入库单 / 应付款。见 db/models/inbound_order.py、db/models/payable.py。
class InboundOrderNotFoundError(BusinessError):
    def __init__(self, message: str = "Inbound order not found"):
        super().__init__(status.HTTP_404_NOT_FOUND, 41701, message)


class InboundSourcePurchaseOrderInvalidError(BusinessError):
    """源 PO 无效:不存在或非 CONFIRMED(入库须基于已确认采购单登记)。"""

    def __init__(self, message: str = "Source purchase order not found or not confirmed"):
        super().__init__(status.HTTP_409_CONFLICT, 41702, message)


class InboundOverReceiptError(BusinessError):
    """超收:累计(非取消入库行,含在途)> 对应 PO 行数量。"""

    def __init__(self, message: str = "Inbound quantity exceeds purchase order line remaining"):
        super().__init__(status.HTTP_409_CONFLICT, 41703, message)


class InboundOrderInvalidTransitionError(BusinessError):
    """状态转移不在 INBOUND_ORDER_TRANSITIONS 矩阵。"""

    def __init__(self, message: str = "Illegal inbound order status transition"):
        super().__init__(status.HTTP_409_CONFLICT, 41704, message)


class InboundOrderNotInTransitError(BusinessError):
    """对非 IN_TRANSIT 入库单执行编辑(整单保存仅在途)。"""

    def __init__(self, message: str = "Inbound order is not in transit"):
        super().__init__(status.HTTP_409_CONFLICT, 41705, message)


class InboundLineNotInPurchaseOrderError(BusinessError):
    """入库行引用的 PO 行不属于该采购单。"""

    def __init__(self, message: str = "Inbound line references a purchase order line not on this PO"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 41706, message)


class InboundOrderEmptyError(BusinessError):
    """空入库单(无行):建单 / 编辑对账后均杜绝。"""

    def __init__(self, message: str = "Inbound order must have at least one line"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 41707, message)


class PayableAllocatedCannotUnreceiveError(BusinessError):
    """撤销入库被拦:对应 payable 已有核销(amount_allocated > 0),不可撤销。"""

    def __init__(self, message: str = "Cannot unreceive: payable has been partially allocated"):
        super().__init__(status.HTTP_409_CONFLICT, 41708, message)


class InboundOrderEditConflictError(BusinessError):
    """乐观锁:expected_updated_at 与库中不一致(整单保存被并发修改抢先)。"""

    def __init__(self, message: str = "Inbound order was modified by someone else"):
        super().__init__(status.HTTP_409_CONFLICT, 41709, message)


class InboundUnreceiveWouldGoNegativeError(BusinessError):
    """撤销入库被拦:货已被出库消费,撤回将使某 (SO, SKU) 可发穿仓(available < 0)。
    0811 后出库单 ISSUED 即正向终点,不能再通过撤销出库释放库存。
    biz_data 带逐 (so,sku) 明细(销售单号/品名/穿仓后可发),镜像 41902 的明细形状。"""

    def __init__(self, message: str = "Cannot unreceive: stock has been outbound",
                 data: Any = None):
        super().__init__(status.HTTP_409_CONFLICT, 41710, message, data=data)


class InboundDuplicateLineError(BusinessError):
    """入库单 payload 同一 PO 行重复出现(一 PO 行一入库行,DB UNIQUE(inb, po_line) 兜底,
    service 前置拒绝——否则打穿到约束成 500)。"""

    def __init__(self, message: str = "Duplicate purchase order line in inbound payload"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 41711, message)


class InboundFinancialBoundaryError(BusinessError):
    """创建入库单后已产生供应商应付,不可再走裸编辑/作废回退。"""

    def __init__(self, message: str = "Inbound order has generated payable; use reverse workflow"):
        super().__init__(status.HTTP_409_CONFLICT, 41712, message)


class PurchaseReturnNotFoundError(BusinessError):
    def __init__(self, message: str = "Purchase return order not found"):
        super().__init__(status.HTTP_404_NOT_FOUND, 41713, message)


class PurchaseReturnSourceInvalidError(BusinessError):
    """采购退货源单无效:MVP 仅允许已确认入库且未形成出库单的链路。"""

    def __init__(self, message: str = "Purchase return source is not eligible"):
        super().__init__(status.HTTP_409_CONFLICT, 41714, message)


class PurchaseReturnOverQtyError(BusinessError):
    """采购退货数量超过入库行剩余可退量。"""

    def __init__(self, message: str = "Purchase return quantity exceeds remaining returnable quantity"):
        super().__init__(status.HTTP_409_CONFLICT, 41715, message)


class PurchaseReturnWouldGoNegativeError(BusinessError):
    """采购退货会导致销售单维度库存可发为负。"""

    def __init__(self, message: str = "Purchase return would make stock negative",
                 data: Any = None):
        super().__init__(status.HTTP_409_CONFLICT, 41716, message, data=data)


class APCreditMemoExceedsOutstandingError(BusinessError):
    """供应商贷项单过账金额超过可冲减的应付金额。"""

    def __init__(self, message: str = "AP credit memo exceeds outstanding payable amount"):
        super().__init__(status.HTTP_409_CONFLICT, 41717, message)


# 模块段 18 = 销售单(SO 状态机)。见 db/models/sales_order.py SalesOrderStatus。
class SalesOrderInvalidTransitionError(BusinessError):
    """状态转移不在 SALES_ORDER_TRANSITIONS 矩阵(重复取消等)。"""

    def __init__(self, message: str = "Illegal sales order status transition"):
        super().__init__(status.HTTP_409_CONFLICT, 41801, message)


class SalesOrderHasActivePurchaseError(BusinessError):
    """取消被拦:存在非 CANCELLED 的采购单(镜像 41609,方向相反)。
    不级联砍下游——解链人工自下而上:先取消全部 PO 再取消 SO。"""

    def __init__(self, message: str = "Cannot cancel a sales order with active purchase orders",
                 data: dict | None = None):
        super().__init__(status.HTTP_409_CONFLICT, 41802, message, data=data)


class SalesOrderHasActiveOutboundError(BusinessError):
    """取消被拦:存在非 CANCELLED 的出库单(镜像 41802,下游轴从采购扩到出库)。
    不级联砍下游——解链人工自下而上:先取消/撤销全部出库单再取消 SO。"""

    def __init__(self, message: str = "Cannot cancel a sales order with active outbound orders",
                 data: dict | None = None):
        super().__init__(status.HTTP_409_CONFLICT, 41803, message, data=data)


# 模块段 19 = 出库单(出库单状态机 + 确认出库可发闸)。见 db/models/outbound_order.py。
class OutboundOrderInvalidTransitionError(BusinessError):
    """状态转移不在 OUTBOUND_ORDER_TRANSITIONS 矩阵。"""

    def __init__(self, message: str = "Illegal outbound order status transition"):
        super().__init__(status.HTTP_409_CONFLICT, 41901, message)


class OutboundInsufficientAvailableError(BusinessError):
    """确认出库被拦:某 (SO, SKU) 本单需发量 > 可发(available = Σ入库 − Σ出库)。
    biz_data 带逐 sku 明细(可发/需发)。"""

    def __init__(self, message: str = "Insufficient available stock to issue outbound", data: Any = None):
        super().__init__(status.HTTP_409_CONFLICT, 41902, message, data=data)


class OutboundLineNotInSalesOrderError(BusinessError):
    """出库行引用的 SO 行不属于该出库单头上的 SO,或行 sku 与 SO 行不一致。"""

    def __init__(self, message: str = "Outbound line references a sales order line not on this SO"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 41903, message)


class OutboundActiveOrderExistsError(BusinessError):
    """同柜同来源 SO 已存在未确认草稿出库单(偏唯一 uq_oborders_shipment_so_draft 兜底)。"""

    def __init__(self, message: str = "A draft outbound order already exists for this shipment and sales order"):
        super().__init__(status.HTTP_409_CONFLICT, 41904, message)


class OutboundSalesOrderNotConfirmedError(BusinessError):
    """出库须锚定 CONFIRMED 销售单(取消/其它态一律拒)。"""

    def __init__(self, message: str = "Outbound requires a confirmed sales order"):
        super().__init__(status.HTTP_409_CONFLICT, 41905, message)


class OutboundShipmentNotOpenError(BusinessError):
    """出库单挂柜/确认出库须柜为 OPEN(已取消或已封柜的柜不可再入单)。"""

    def __init__(self, message: str = "Outbound requires an open shipment"):
        super().__init__(status.HTTP_409_CONFLICT, 41906, message)


class ReceivableAllocatedCannotRevertError(BusinessError):
    """历史错误:0811 后出库单不再允许撤销,保留 code 兼容旧调用方。"""

    def __init__(self, message: str = "Cannot revert outbound: issued outbound is terminal"):
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
    """历史错误:0811 后出库单不再允许撤销,保留 code 兼容旧调用方。"""

    def __init__(self, message: str = "Cannot revert outbound: issued outbound is terminal"):
        super().__init__(status.HTTP_409_CONFLICT, 41910, message)


class OutboundOrderEmptyError(BusinessError):
    """空出库单(无行):建单 / 编辑对账后 / 确认前均杜绝(镜像采购 41608 / 入库 41707)。
    service 兜底 —— API schema 挡空行,但 service 直调若放行 0 行出库,会在确认时生成
    0 金额应收、并让柜误判「非空」占用槽位。守卫落最强层。"""

    def __init__(self, message: str = "Outbound order must have at least one line"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 41911, message)


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
    """封柜确认被拦:柜内存在草稿(DRAFT)出库单——只有已确认(已扣库存)的出库单代表柜内真实
    货物,草稿只是意图。biz_data 带草稿单号列表({"draft_nos": [...]})。"""

    def __init__(self, message: str = "Cannot load: shipment has draft outbound orders",
                 data: Any = None):
        super().__init__(status.HTTP_409_CONFLICT, 42003, message, data=data)


class ShipmentEmptyCannotLoadError(BusinessError):
    """封柜确认被拦:空柜(无任何非 CANCELLED 出库单)不可封柜。"""

    def __init__(self, message: str = "Cannot load an empty shipment"):
        super().__init__(status.HTTP_409_CONFLICT, 42004, message)


class ShipmentFieldNotEditableError(BusinessError):
    """编辑门禁:提交值 ≠ 库中值,且该字段 ∉ 当前状态可编辑集(diff 式门禁,
    SHIPMENT_EDITABLE_FIELDS_BY_STATUS 单一源头)。biz_data 带被拒字段名({"fields": [...]})。
    与 42002(非法转移)分码:是两种用户情境(镜像出库 41901/41908 分码先例)。
    409:请求本身合法,被拒源于资源当前状态(与 41901 先例及 REST 语义齐)。"""

    def __init__(self, message: str = "Field not editable in current shipment status",
                 data: Any = None):
        super().__init__(status.HTTP_409_CONFLICT, 42005, message, data=data)


class ShipmentEditConflictError(BusinessError):
    """乐观锁:expected_updated_at 与库中不一致(柜被他人改后 stale 提交)。镜像 41908,
    前端据此提示「已被他人修改,请刷新」而非「状态非法」。"""

    def __init__(self, message: str = "Shipment was modified by someone else"):
        super().__init__(status.HTTP_409_CONFLICT, 42006, message)


# 物流轨迹事件(段 20 延用:发运柜子资源,不新开段)。见 db/models/shipment_event.py。
# 42007 撤离港被拦(柜下有活动事件)/ 42008 非 DEPARTED 柜不可录改删 /
# 42009 重复到港 / 42010 事件不属于该柜。
class ShipmentHasActiveLogisticsEventError(BusinessError):
    """撤离港被拦:柜下存在活动物流事件(deleted_at IS NULL)。离港是物流轨迹的起点,
    撤离港会清 atd,须先作废该柜全部物流事件再撤。"""

    def __init__(self, message: str = "Cannot undepart: shipment has active logistics events"):
        super().__init__(status.HTTP_409_CONFLICT, 42007, message)


class ShipmentNotDepartedError(BusinessError):
    """录/改/作废物流事件被拦:发运柜非 DEPARTED——物流轨迹从离港后接手,未离港无在途里程碑。"""

    def __init__(self, message: str = "Cannot manage logistics events: shipment not departed"):
        super().__init__(status.HTTP_409_CONFLICT, 42008, message)


class ShipmentEventDuplicateArrivedError(BusinessError):
    """重复到港:该柜已有一条活动 ARRIVED 事件(到港是终点,每柜至多一条)。"""

    def __init__(self, message: str = "Shipment already has an active arrived event"):
        super().__init__(status.HTTP_409_CONFLICT, 42009, message)


class ShipmentEventNotOnShipmentError(BusinessError):
    """物流事件不属于路径上的发运柜(镜像出库 41903:子资源越柜访问)。"""

    def __init__(self, message: str = "Logistics event does not belong to this shipment"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 42010, message)


# 报关记录(段 20 延用:发运柜子资源,回填结果,不新开段)。见 db/models/customs_declaration.py。
# 42011 撤封柜带活动报关 / 42012 柜态不可报关 / 42013 重复活动报关 / 42014 报关越柜 / 42015 编辑冲突 /
# 42016 报关单号已被占用。
class ShipmentHasActiveCustomsError(BusinessError):
    """撤封柜(LOADED→OPEN)被拦:柜下存在活动报关记录。柜内容变了申报即失效,
    须先作废报关再撤封柜(同 42007 撤离港被活动物流事件拦的范式)。"""

    def __init__(self, message: str = "Cannot unload: shipment has an active customs declaration"):
        super().__init__(status.HTTP_409_CONFLICT, 42011, message)


class CustomsShipmentNotDeclarableError(BusinessError):
    """录/改/作废报关被拦:柜状态非 LOADED/DEPARTED(报关发生在封柜后、到货前)。"""

    def __init__(self, message: str = "Cannot manage customs: shipment not loaded or departed"):
        super().__init__(status.HTTP_409_CONFLICT, 42012, message)


class CustomsDuplicateActiveError(BusinessError):
    """该柜已有一条活动报关记录(整柜一次报关,偏唯一;纠错请软删重录)。"""

    def __init__(self, message: str = "Shipment already has an active customs declaration"):
        super().__init__(status.HTTP_409_CONFLICT, 42013, message)


class CustomsNotOnShipmentError(BusinessError):
    """报关记录不属于路径上的发运柜(仅跨柜语义;不存在/已删走 404)。镜像 42010。"""

    def __init__(self, message: str = "Customs declaration does not belong to this shipment"):
        super().__init__(status.HTTP_400_BAD_REQUEST, 42014, message)


class CustomsEditConflictError(BusinessError):
    """乐观锁:expected_updated_at 与库中不一致(报关记录被他人改后 stale 提交)。
    镜像 42006:前端据此提示「已被他人修改,请刷新」。"""

    def __init__(self, message: str = "Customs declaration was modified by someone else"):
        super().__init__(status.HTTP_409_CONFLICT, 42015, message)


class CustomsDeclarationNoTakenError(BusinessError):
    """报关单号已被另一条活动报关记录占用(全局活动期唯一,跨柜同号即录错;
    偏唯一 uq_customs_active_declno 兜底并发)。纠错口 = 软删占用记录或改单号。"""

    def __init__(self, message: str = "Declaration number already used by another declaration"):
        super().__init__(status.HTTP_409_CONFLICT, 42016, message)


# ── 附件域(段 21;单据扫描件基建。见 db/models/attachment.py)──────────────
class AttachmentTypeNotAllowedError(BusinessError):
    """42101 — 附件类型不允许(不落允许族:扩展名/声明 MIME/嗅探 MIME 任一不匹配)。"""

    def __init__(self, message: str = "Attachment type not allowed"):
        super().__init__(422, 42101, message)


class AttachmentTooLargeError(BusinessError):
    """42102 — 附件超大小上限。"""

    def __init__(self, message: str = "Attachment too large"):
        super().__init__(413, 42102, message)


class AttachmentOrphanQuotaError(BusinessError):
    """42103 — 孤儿附件配额超限(单用户活动孤儿数量/字节双限)。"""

    def __init__(self, message: str = "Orphan attachment quota exceeded"):
        super().__init__(422, 42103, message)


class AttachmentUnavailableError(BusinessError):
    """42104 — 附件不可用(不存在 / 已删 / 已归属他单 / 非本人孤儿 / 已过 TTL)。
    统一码不暴露存在性(下载 scope 拒绝、关联校验拒绝、查无一律走此)。"""

    def __init__(self, message: str = "Attachment unavailable"):
        super().__init__(status.HTTP_404_NOT_FOUND, 42104, message)


class AttachmentTooManyError(BusinessError):
    """42105 — 单报关记录关联附件数超上限(10)。"""

    def __init__(self, message: str = "Too many attachments, maximum 10 allowed"):
        super().__init__(422, 42105, message)


# ---------- 财务(核销引擎,模块段 22)----------


class AllocationExceedsSourceError(BusinessError):
    """42201 — 核销金额超收款/付款单未分配金额。"""

    def __init__(self, message: str = "Allocation exceeds source unallocated balance"):
        super().__init__(status.HTTP_409_CONFLICT, 42201, message)


class AllocationExceedsAccountError(BusinessError):
    """42202 — 核销金额超账未结金额。"""

    def __init__(self, message: str = "Allocation exceeds account outstanding amount"):
        super().__init__(status.HTTP_409_CONFLICT, 42202, message)


class AllocationCurrencyMismatchError(BusinessError):
    """42203 — 跨币种核销(收付币种 ≠ 账币种)。"""

    def __init__(self, message: str = "Currency mismatch between receipt/payment and account"):
        super().__init__(status.HTTP_409_CONFLICT, 42203, message)


class AllocationCounterpartyMismatchError(BusinessError):
    """42204 — 客户/供应商不匹配(收款客户 ≠ 应收客户,付款供应商 ≠ 应付供应商)。"""

    def __init__(self, message: str = "Counterparty mismatch"):
        super().__init__(status.HTTP_409_CONFLICT, 42204, message)


class AllocationReverseNotFoundError(BusinessError):
    """42205 — 反核销:核销记录不存在 / 已反核销(幂等)。"""

    def __init__(self, message: str = "Allocation not found or already reversed"):
        super().__init__(status.HTTP_404_NOT_FOUND, 42205, message)


class AccountVoidedCannotAllocateError(BusinessError):
    """42206 — 账已作废(voided_at 非空),不可核销。"""

    def __init__(self, message: str = "Account is voided, cannot allocate"):
        super().__init__(status.HTTP_409_CONFLICT, 42206, message)


class ReceiptNotUnclaimedError(BusinessError):
    """42207 — 认领 / 人工核销前置:收款单非 UNCLAIMED(已认领不可重认领)或
    未认领单不可人工核销(customer_id 为空)。"""

    def __init__(self, message: str = "Receipt is not in UNCLAIMED state"):
        super().__init__(status.HTTP_409_CONFLICT, 42207, message)


class SourceHasActiveAllocationsError(BusinessError):
    """42208 — 收款/付款单已有活动核销,不可作废(先反核销)。"""

    def __init__(self, message: str = "Receipt/Payment has active allocations, reverse first"):
        super().__init__(status.HTTP_409_CONFLICT, 42208, message)


class SourceVoidedError(BusinessError):
    """42209 — 收款/付款单已作废,不可认领/核销。"""

    def __init__(self, message: str = "Receipt/Payment is voided"):
        super().__init__(status.HTTP_409_CONFLICT, 42209, message)


class AllocationPairAlreadyActiveError(BusinessError):
    """42210 — 同 (收/付款单, 账) 已有活动核销(偏唯一契约:一对至多一条,部分核销靠 amount)。
    先反核销该条,再重核即得新的取满额。单线程可达(反核销其它账回血后同对重核),
    引擎前置判;偏唯一 uq_*_alloc_active 兜底并发,service 层同映射此码。"""

    def __init__(self, message: str = "An active allocation already exists for this pair, reverse it first"):
        super().__init__(status.HTTP_409_CONFLICT, 42210, message)


def success(data: Any = None, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data}
