import type {
  ReverseGoodsStatus,
  ReverseRequestStatus,
  ReverseSupplierResolution,
} from "@/lib/reverseRequest";

export const REVERSE_REQUEST_STATUS_META: Record<ReverseRequestStatus, { label: string; color: string }> = {
  PENDING_REVIEW: { label: "待审核", color: "processing" },
  APPROVED: { label: "待处置", color: "warning" },
  REJECTED: { label: "已驳回", color: "default" },
  COMPLETED: { label: "已关闭", color: "success" },
};

export const REVERSE_GOODS_STATUS_META: Record<ReverseGoodsStatus, { label: string; color: string }> = {
  IN_TRANSIT: { label: "未到仓", color: "processing" },
  RECEIVED: { label: "已入库", color: "success" },
};

export const REVERSE_SUPPLIER_RESOLUTION_LABEL: Record<ReverseSupplierResolution, string> = {
  SUPPLIER_ACCEPTS_RETURN: "供应商接受退回",
  COMPANY_BEAR_LOSS: "供应商不接受,公司承担",
};

export const reverseRequestApprovable = (s: ReverseRequestStatus) => s === "PENDING_REVIEW";
export const reverseRequestClosable = (s: ReverseRequestStatus) => s === "APPROVED";
