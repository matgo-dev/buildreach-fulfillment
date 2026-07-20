// 后端错误码 → 中文 toast 的统一归口。
// 各域 code 表在此分域声明、合并进单一注册表(数字 biz_code 全局唯一,由后端 exceptions.py 段管辖);
// 未注册的 code 沿用后端 message,非 Error 兜底 fallback。
import { ApiError } from "./api";

// 采购域(镜像 exceptions.py 段 15/16)。未列出的沿用后端 message。
const PURCHASE_ERROR_MESSAGES: Record<number, string> = {
  41603: "数量超过销售单剩余额度",
  41606: "供应商已停用,不可选用",
  41604: "来源销售单无效",
  41605: "采购单已被他人修改,请刷新后重试",
  41607: "仅草稿可编辑 / 删除",
  41608: "采购单至少需要一行",
  41501: "供应商不存在",
};

// 入库域(镜像 exceptions.py 段 16/17)。未列出的沿用后端 message。
const INBOUND_ERROR_MESSAGES: Record<number, string> = {
  41609: "该采购单存在活动入库单,不可取消",
  41701: "入库单不存在",
  41702: "来源采购单无效或未确认",
  41703: "入库数量超过采购单剩余可收额度",
  41704: "非法的入库单状态流转",
  41705: "仅在途入库单可编辑",
  41706: "入库行引用的采购行不属于该采购单",
  41707: "入库单至少需要一行",
  41708: "对应应付款已有核销,不可撤销入库",
  41709: "入库单已被他人修改,请刷新后重试",
  41711: "入库单行重复引用同一采购单行",
};

// 出库 / 发运柜域(镜像 exceptions.py 段 419xx 出库 / 420xx 柜 / 41710 入库补 / 41412 报价补)。
const OUTBOUND_ERROR_MESSAGES: Record<number, string> = {
  41901: "非法的出库单状态流转",
  41902: "可发数量不足",
  41903: "出库行不属于该销售单",
  41904: "该柜内此销售单已有活动出库单",
  41905: "来源销售单未确认,不可出库",
  41906: "发运柜不在组柜中状态",
  41907: "对应应收款已有核销,不可撤销出库",
  41908: "出库单已被他人修改,请刷新后重试",
  41909: "出库单行重复引用同一销售单行",
  41412: "报价单同 SKU 不可重复",
  42001: "柜下存在活动出库单,不可取消",
  42002: "非法的发运柜状态流转",
  42003: "柜内存在草稿出库单,请先确认或移除",
  42004: "空柜不可装柜",
  42005: "当前状态不可修改该字段",
  42006: "发运柜已被他人修改,请刷新后重试",
  41910: "柜已装柜/发运,请先撤装柜再撤销出库",
  41710: "库存已被出库消费,请先撤销出库再撤销入库",
};

const BIZ_ERROR_MESSAGES: Record<number, string> = {
  ...PURCHASE_ERROR_MESSAGES,
  ...INBOUND_ERROR_MESSAGES,
  ...OUTBOUND_ERROR_MESSAGES,
};

/** 统一错误提示入口:ApiError 且 code 已注册 → 注册文案;其它 Error → e.message;非 Error → fallback。 */
export function resolveBizError(e: unknown, fallback: string): string {
  if (e instanceof ApiError && BIZ_ERROR_MESSAGES[e.code]) return BIZ_ERROR_MESSAGES[e.code];
  return e instanceof Error ? e.message : fallback;
}
