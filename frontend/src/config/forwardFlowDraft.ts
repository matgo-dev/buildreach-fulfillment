import type { GuideIconKey, GuideRole } from "@/config/guideFlow";

export type DraftFlowCategory = "DOCUMENT" | "GOODS" | "MONEY" | "BOUNDARY";
export type DraftFlowBand = "ORDERING" | "FULFILLMENT";

export interface DraftFlowNode {
  id: string;
  iconKey: GuideIconKey;
  action: string;
  docName: string;
  role: GuideRole;
  category: DraftFlowCategory;
  band: DraftFlowBand;
  inEdgeLabel?: string;
  note: string;
  sideEffects?: string[];
  boundary?: boolean;
}

export interface DraftMoneyBranch {
  id: string;
  anchorId: string;
  iconKey: GuideIconKey;
  action: string;
  docName: string;
  role: GuideRole;
  inEdgeLabel: string;
  note: string;
  settlement: string;
}

export const DRAFT_FLOW_BANDS: { id: DraftFlowBand; title: string }[] = [
  { id: "ORDERING", title: "第一段:接单、订货与发货确认" },
  { id: "FULFILLMENT", title: "第二段:到仓、装柜与出运" },
];

export const DRAFT_FLOW_NODES: DraftFlowNode[] = [
  {
    id: "quotation",
    iconKey: "quotation",
    action: "给客户报价",
    docName: "报价管理",
    role: "SALES",
    category: "DOCUMENT",
    band: "ORDERING",
    note: "销售把客户、商品、数量、价格录成报价单。客户没确认前,仍是内部商谈结果。",
  },
  {
    id: "salesOrder",
    iconKey: "salesOrder",
    action: "客户确认订单",
    docName: "销售单",
    role: "SALES",
    category: "DOCUMENT",
    band: "ORDERING",
    inEdgeLabel: "客户点头",
    note: "报价锁档后转销售单。后续采购、入库、出库都从这张销售单追溯产品、价格和数量。",
  },
  {
    id: "purchaseOrder",
    iconKey: "purchaseOrder",
    action: "向供应商订货",
    docName: "采购单",
    role: "PURCHASER",
    category: "DOCUMENT",
    band: "ORDERING",
    inEdgeLabel: "按单采购",
    note: "采购单仍是供应商侧订货依据。若还没有外部事实发生,可按基础回退取消。",
  },
  {
    id: "dispatchConfirm",
    iconKey: "inbound",
    action: "确认发货/拉货",
    docName: "入库单创建",
    role: "LOGISTICS",
    category: "BOUNDARY",
    band: "ORDERING",
    inEdgeLabel: "供应商开始动货",
    note: "草案里,入库单创建不再只是登记在途,而是表示供应商已发货或我们已去拉货;这个节点只产生供应商应付。",
    sideEffects: ["产生供应商应付", "客户预收独立存在", "进入不可简单回退段"],
    boundary: true,
  },
  {
    id: "receiveInbound",
    iconKey: "inventory",
    action: "确认入库,库存更新",
    docName: "入库单 / 库存",
    role: "LOGISTICS",
    category: "GOODS",
    band: "FULFILLMENT",
    note: "货到货代仓后确认入库,库存随之更新;这个节点不再新产生应付,也不产生客户应收。",
    sideEffects: ["形成销售单维度库存"],
  },
  {
    id: "shipmentOpen",
    iconKey: "shipmentOpen",
    action: "开发运柜",
    docName: "发运柜",
    role: "LOGISTICS",
    category: "GOODS",
    band: "FULFILLMENT",
    inEdgeLabel: "准备装柜",
    note: "开一个组柜中的柜子,作为后续出库单装载容器。",
  },
  {
    id: "outboundCreated",
    iconKey: "outbound",
    action: "创建出库单",
    docName: "出库单",
    role: "LOGISTICS",
    category: "BOUNDARY",
    band: "FULFILLMENT",
    inEdgeLabel: "选择货和柜",
    note: "出库单一旦形成,原正向流程不可逆;后续退货退款必须新建逆向流程。",
    sideEffects: ["正向流程终止边界"],
    boundary: true,
  },
  {
    id: "outboundIssued",
    iconKey: "outbound",
    action: "装柜&出库",
    docName: "确认出库",
    role: "LOGISTICS",
    category: "GOODS",
    band: "FULFILLMENT",
    inEdgeLabel: "货装进柜",
    note: "确认出库负责扣减库存和确认装柜事实,同时继续作为客户应收产生节点。",
    sideEffects: ["扣减库存", "产生客户应收"],
  },
  {
    id: "shipment",
    iconKey: "shipment",
    action: "封柜、离港",
    docName: "发运柜",
    role: "LOGISTICS",
    category: "GOODS",
    band: "FULFILLMENT",
    inEdgeLabel: "柜装满",
    note: "封柜后柜内货物冻结,离港后继续登记物流和报关节点。",
  },
  {
    id: "customs",
    iconKey: "customs",
    action: "物流、报关清关",
    docName: "发运柜/报关",
    role: "LOGISTICS",
    category: "GOODS",
    band: "FULFILLMENT",
    inEdgeLabel: "货物出运",
    note: "后续只记录物流在途、到港、报关和放行信息。",
  },
];

export const DRAFT_MONEY_BRANCHES: DraftMoneyBranch[] = [
  {
    id: "receivable",
    anchorId: "outboundIssued",
    iconKey: "receivable",
    action: "客户欠我们钱",
    docName: "应收款",
    role: "FINANCE",
    inEdgeLabel: "确认出库时生成",
    note: "客户应收继续保持在确认出库/装柜出库时产生。客户如果已提前付款,先作为客户预收存在,到应收生成后再核销。",
    settlement: "用收款单或既有预收核销",
  },
  {
    id: "payable",
    anchorId: "dispatchConfirm",
    iconKey: "payable",
    action: "我们欠供应商钱",
    docName: "应付款",
    role: "FINANCE",
    inEdgeLabel: "入库单创建时生成",
    note: "应付从原来的确认入库前移到入库单创建/发货拉货确认。已付给供应商的钱后续核销到这笔应付。",
    settlement: "后续用付款单核销;先付款则形成预付再核销",
  },
];
