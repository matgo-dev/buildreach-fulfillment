// 逆向/撤销导览页的数据源。只描述当前已落地的基础逆向规则,不承诺退货退款等未定业务流程。
// 页面层负责渲染;这里保持纯数据,避免把业务文案散落在组件里。

export type ReverseSeverity = "normal" | "money" | "goods" | "external";

export interface ReverseStep {
  id: string;
  title: string;
  owner: string;
  when: string;
  result: string;
  severity: ReverseSeverity;
  blocks?: string;
  children?: ReverseStep[];
}

export const REVERSE_FLOW_PRINCIPLES = [
  "先撤下游,再撤上游;系统不会自动级联作废正式单据。",
  "草稿/在途类单据可以取消或作废;已确认出库代表正向履约终点,不能回退原单据。",
  "库存当前是按销售单履约库存,由已入库和已出库状态实时派生;不是仓库自由库存账。",
  "作废、撤销、反核销都保留业务痕迹;当前是 P0 基础逆向留痕,不是完整财务凭证或库存流水账。",
];

export const REVERSE_FLOW_TREES: ReverseStep[] = [
  {
    id: "cancel-sales-order",
    title: "取消销售单",
    owner: "销售视角",
    when: "客户确认后的销售单需要整体退回重做。",
    result: "销售单进入已取消;来源报价回到锁档,可修改后重新转销售。",
    severity: "normal",
    blocks: "存在活动采购单或活动出库单时会被拒绝。",
    children: [
      {
        id: "cancel-purchase-order",
        title: "先取消采购单",
        owner: "采购视角",
        when: "销售单下还有未取消的采购单。",
        result: "采购单进入已取消;释放销售单行的采购覆盖量。",
        severity: "normal",
        blocks: "采购单下存在活动入库单时会被拒绝。",
        children: [
          {
            id: "void-in-transit-inbound",
            title: "在途入库单不可直接作废",
            owner: "采购/物流视角",
            when: "供应商已发货/我方已拉货并创建入库单后,已产生供应商应付。",
            result: "当前线上入口会被拦截;需要走履约中取消/逆向申请承载实物与财务处理。",
            severity: "goods",
          },
          {
            id: "unreceive-inbound",
            title: "撤销已入库入库单",
            owner: "采购/物流视角",
            when: "货已经确认入库,但业务上需要回到在途状态。",
            result: "入库单回到在途;库存派生数量回落;对应应付款保持活动。",
            severity: "goods",
            blocks: "货已被确认出库消费时不可撤销入库。",
          },
        ],
      },
      {
        id: "cancel-outbound-order",
        title: "先处理出库单",
        owner: "物流视角",
        when: "销售单下还有未取消的出库单。",
        result: "草稿出库单可取消;已出库单不可回退原流程。当前系统暂不支持出库后线上冲正,需联系管理员处理。",
        severity: "goods",
        blocks: "已出库单会阻止原销售单取消;这是履约事实锁定,不是按钮权限问题。",
        children: [
          {
            id: "reverse-receipt-allocation",
            title: "反核销收款",
            owner: "财务视角",
            when: "出库前的基础回退涉及应收/收款纠错时。",
            result: "指定核销记录被反核销;收款单未分配余额和应收款余额恢复对应金额。已出库后的客户退货不靠反核销回退原单。",
            severity: "money",
          },
          {
            id: "unwind-shipment",
            title: "柜状态只影响物流纠错",
            owner: "物流视角",
            when: "发运柜封柜、离港、报关或物流轨迹录入错误。",
            result: "撤离港后回到已封柜;撤封柜后回到 OPEN。柜状态回退不再解锁已出库单撤销。",
            severity: "external",
            blocks: "有活动物流节点时先作废物流节点;有活动报关记录时先作废报关记录。",
            children: [
              {
                id: "void-logistics-event",
                title: "作废物流节点",
                owner: "物流视角",
                when: "柜已离港后录入过中转或到港节点。",
                result: "该节点退出当前有效时间线;底层软删留痕。",
                severity: "external",
              },
              {
                id: "void-customs-declaration",
                title: "作废报关记录",
                owner: "物流/报关视角",
                when: "柜已封柜或离港后录入过报关记录。",
                result: "活动报关记录失效;附件同步归档;之后可重新录入。",
                severity: "external",
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: "void-receipt-payment",
    title: "作废收款单/付款单",
    owner: "财务视角",
    when: "收付款记录需要退出当前有效状态,后续按实际情况重录或重新核销。",
    result: "收付款单作废留痕,默认列表不再进入活动结算。",
    severity: "money",
    blocks: "存在活动核销记录时必须先逐条反核销。",
  },
];

export const REVERSE_FLOW_BOUNDARIES = [
  "这张图只覆盖出库确认前的取消、撤销、作废、反核销等基础逆向动作。",
  "出库确认后原流程不可逆;当前系统暂不支持出库后退货、退款、贷项、跨期冲销或库存恢复。",
  "出库后异常由管理员按受控方案线下登记、评估影响并处理;0812 退货退款单据上线后再改为线上闭环。",
  "报关和物流目前采用软作废退出当前有效视图;完整历史可视化属于后续增强,不靠审计日志替代业务页面。",
  "如果未来货可以脱离原销售单重新可售,库存模型需要升级为仓库维度真实库存账本。",
];
