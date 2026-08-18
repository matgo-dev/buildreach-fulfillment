// 平台导览页(/guide)的内容单一源头。
// 纯数据、无 JSX:图标以 iconKey 承载,映射在 components/guide/guideIcons.tsx。
// 文案面向非技术新同事,不出现「状态机/派生/乐观锁」等实现词汇。
// 事实依据 = docs/契约/ 下各步设计契约;改流程时同步改这里。
import { ROLE_META } from "@/lib/user";

export type GuideRole = keyof typeof ROLE_META;

/** 节点所在层:主链 / 资金流支线 / 链外前置主数据。后两层默认折叠。 */
export type GuideLayer = "MAIN" | "MONEY" | "MASTER";

/** 主链两行蛇形的分区带。 */
export type GuideBand = "SOURCING" | "DELIVERY";

/**
 * 节点语义域(左边色条 + 图例用):基础资料 / 业务单据 / 货(库存)/ 钱(财务)。
 * 颜色只引用现有 tokens(colorToken),不发明新色值、不铺满卡片——遵 DESIGN.md「绿点睛非铺满」。
 */
export type GuideCategory = "MASTER_DATA" | "DOCUMENT" | "GOODS" | "MONEY";

export type GuideIconKey =
  | "quotation" | "salesOrder" | "purchaseOrder" | "inbound" | "inventory"
  | "outbound" | "shipmentOpen" | "shipment" | "logistics" | "customs"
  | "receivable" | "receipt" | "payable" | "payment"
  | "product" | "customer" | "supplier";

export interface GuideNode {
  id: string;
  iconKey: GuideIconKey;
  /** 主标题:人话动作句 */
  action: string;
  /** 副标题:系统里的单据名/菜单名 */
  docName: string;
  role: GuideRole;
  layer: GuideLayer;
  /** 仅 MAIN 层有值 */
  band?: GuideBand;
  /** 仅 MONEY 层有值:这个节点挂在哪个节点下面 */
  anchorId?: string;
  /** 进入本节点那条边的标签(人话,不写会计记号)。链首无值。 */
  inEdgeLabel?: string;
  /** hover 一句话速览 */
  tooltip: string;
  /** 抽屉①这一步在做什么 */
  what: string;
  /** 抽屉③上下游 + 在哪个菜单里找 */
  fromTo: string;
  /** 抽屉④做完之后系统里发生了什么 */
  effect: string;
  /** 「跟一单货走一遍」的旁白;不参与叙事的节点为 null */
  narration: string | null;
}

export const GUIDE_BANDS: { id: GuideBand; title: string }[] = [
  { id: "SOURCING", title: "第一段:接单与备货" },
  { id: "DELIVERY", title: "第二段:发货与出运" },
];

export const GUIDE_NODES: GuideNode[] = [
  // ---------- 链外前置主数据 ----------
  {
    id: "product",
    iconKey: "product",
    action: "先把卖什么建好",
    docName: "商品目录",
    role: "PRODUCT_OPERATOR",
    layer: "MASTER",
    tooltip: "报价挑货之前,商品和它的规格得先在系统里。",
    what: "商品分两层:一个「商品」是一个型号(比如某款瓷砖),它下面挂着若干「规格」(尺寸、颜色等)。报价、采购、库存里挑的都是具体规格,不是型号。",
    fromTo: "这是链外的基础资料,报价之前就要建好。在左侧菜单「基础资料」→「商品目录」里维护。",
    effect: "商品停用之后,新报价就挑不到它了,但已经开过的老单据不受影响。",
    narration: null,
  },
  {
    id: "customer",
    iconKey: "customer",
    action: "先把卖给谁建好",
    docName: "客户",
    role: "SALES",
    layer: "MASTER",
    tooltip: "报价单的抬头只能从客户档案里选,不能手打。",
    what: "客户档案。报价单、销售单的客户都从这里选,保证同一个客户在系统里只有一份资料。",
    fromTo: "链外的基础资料,报价之前建好。在左侧菜单「基础资料」→「客户」里维护。",
    effect: "已经被单据用过的客户不能删掉,只能停用 —— 否则老单据会找不到抬头。",
    narration: null,
  },
  {
    id: "supplier",
    iconKey: "supplier",
    action: "先把找谁买建好",
    docName: "供应商",
    role: "PURCHASER",
    layer: "MASTER",
    tooltip: "采购单的供应商只能从档案里选。",
    what: "供应商档案。采购单、应付款、付款单都指向这里。",
    fromTo: "链外的基础资料,采购之前建好。在左侧菜单「基础资料」→「供应商」里维护。",
    effect: "已经被采购单用过的供应商不能删掉,只能停用。",
    narration: null,
  },

  // ---------- 主链:第一段 接单与备货 ----------
  {
    id: "quotation",
    iconKey: "quotation",
    action: "给客户报价",
    docName: "报价管理",
    role: "SALES",
    layer: "MAIN",
    band: "SOURCING",
    tooltip: "销售把已经谈定的量和价录进系统,形成一张报价单。",
    what: "客户要什么货、多少量、什么价,线下已经谈定了;销售把谈定的结果录进系统,形成一张报价单。一个规格一行 —— 价格是谈出来的,系统不算阶梯价。",
    fromTo: "上一步:客户和商品要先在系统里建好。下一步:客户点头后把报价「锁档」,再转成销售单。在左侧菜单「销售」→「报价管理」里操作。",
    effect: "报价单刚建出来是「草稿」,可以随便改;客户确认后销售把它「锁档」,冻成不能再改的基准。谈崩了就作废,不是删掉 —— 留个痕。",
    narration: "客户要 200 套瓷砖,价格已经在线下谈定。销售把它录成一张报价单。",
  },
  {
    id: "salesOrder",
    iconKey: "salesOrder",
    action: "客户确认,订单成立",
    docName: "销售单",
    role: "SALES",
    layer: "MAIN",
    band: "SOURCING",
    inEdgeLabel: "客户点头,锁档转单",
    tooltip: "锁档的报价单一键转成销售单,这一单正式成立。",
    what: "报价锁档之后转成销售单。销售单是后面一切的源头 —— 采购、入库、出库、发运全都挂在它下面。",
    fromTo: "上一步:已锁档的报价单。下一步:采购员照着它去向供应商订货。在左侧菜单「销售」→「销售单」里查看。",
    effect: "一张报价单只能转一次,转完撤不回来。想改就得整单取消,重新走一遍。",
    narration: "客户确认了,销售把报价锁档并转成销售单 —— 这一单正式成立。",
  },
  {
    id: "purchaseOrder",
    iconKey: "purchaseOrder",
    action: "向供应商订货",
    docName: "采购单",
    role: "PURCHASER",
    layer: "MAIN",
    band: "SOURCING",
    inEdgeLabel: "照销售单去订货",
    tooltip: "采购员按销售单上的需求,向供应商下采购单。",
    what: "我们是「按单采购」—— 先有销售单才有采购单,不提前囤货。采购单的每一行都挂在销售单的某一行下面,系统会挡住订超量。",
    fromTo: "上一步:已成立的销售单。下一步:供应商发货后登记入库单。在左侧菜单「采购」→「采购单」里操作。",
    effect: "采购单刚建出来是「草稿」可以改;一旦「确认」就是正式下给供应商的单,不能再改,只能取消。货已经在途或已经收到的,不让取消。",
    narration: "采购员看到这张销售单,向瓷砖厂下了一张 200 套的采购单并确认。",
  },
  {
    id: "inbound",
    iconKey: "inbound",
    action: "登记在途入库单",
    docName: "入库单",
    role: "LOGISTICS",
    layer: "MAIN",
    band: "SOURCING",
    inEdgeLabel: "供应商发货",
    tooltip: "现有流程里,供应商发货后先登记一张在途入库单。",
    what: "现有流程分两步:供应商发货后,先登记一张「在途」入库单,记录承运信息、物流单号和预计/实际到货信息。这个动作只是登记在途事实。",
    fromTo: "上一步:已确认的采购单(只有确认过的采购单才能建入库单)。下一步:货到货代仓并清点后,再确认入库。在左侧菜单「仓储物流」→「入库单」里操作。",
    effect: "现有规则下,创建入库单不产生库存,但会产生供应商应付。它说明货已经在路上,也进入不可简单回退段。",
    narration: "瓷砖厂发货后,仓储先登记一张在途入库单,记录这批货正在路上。",
  },
  {
    id: "inboundReceive",
    iconKey: "inventory",
    action: "确认入库,库存更新",
    docName: "入库单 / 库存",
    role: "LOGISTICS",
    layer: "MAIN",
    band: "SOURCING",
    inEdgeLabel: "货到货代仓",
    tooltip: "货到货代仓并点数无误后,确认入库,库存随之更新。",
    what: "货真的到货代仓之后,仓储/物流清点数量,确认无误后把在途入库单「确认入库」。",
    fromTo: "上一步:在途入库单。下一步:要发货时开出库单。在左侧菜单「仓储物流」→「入库单」详情里确认,库存页可查看结果。",
    effect: "现有规则下,确认入库的那一刻才产生库存,不再新产生应付。客户侧应收仍然等确认出库时才产生。",
    narration: "货到货代仓后,仓储点清 200 套并确认入库,这批货才进入库存。",
  },

  // ---------- 主链:第二段 发货与出运 ----------
  {
    id: "shipmentOpen",
    iconKey: "shipmentOpen",
    action: "先开一个发运柜",
    docName: "发运柜",
    role: "LOGISTICS",
    layer: "MAIN",
    band: "DELIVERY",
    inEdgeLabel: "货齐了,准备出运",
    tooltip: "出货前先开一个空柜,后面出库的货往里装。",
    what: "我们是整柜出运,所以出货前要先开一个发运柜(集装箱)当容器。柜子刚开出来是「组柜中」,空的,等着出库的货往里装。一个柜可以装多张出库单 —— 不同销售单的货可以拼一个柜。",
    fromTo: "上一步:库存里有可发的货。下一步:开好柜后,建出库单把货取出来挂到这个柜上。在左侧菜单「仓储物流」→「发运柜」里操作。",
    effect: "开出来的空柜处于「组柜中」,可以往里挂出库单。只要还没装东西,这个柜可以直接取消。",
    narration: "要发货了。货代先开一个去坦桑的发运柜(空柜),准备组货。",
  },
  {
    id: "outbound",
    iconKey: "outbound",
    action: "装柜&出库",
    docName: "出库单",
    role: "LOGISTICS",
    layer: "MAIN",
    band: "DELIVERY",
    inEdgeLabel: "往柜里装货",
    tooltip: "从某张销售单的库存里取货,挂到已开好的发运柜上。",
    what: "出库单刚建出来是草稿,可以改;「确认出库」之后货就从库存里扣掉了。出库单必须挂在一个已经开好的发运柜上 —— 因为我们是整柜出运,得先有柜才能装。",
    fromTo: "上一步:已经开好一个「组柜中」的发运柜。下一步:柜子装满后封柜离港。在左侧菜单「仓储物流」→「出库单」里操作。",
    effect: "确认出库的那一刻库存减少,同时系统自动记下「客户欠我们这笔钱」。发错了可以撤销,但客户已经付过款的那笔不让撤。",
    narration: "仓库开一张出库单,把 200 套瓷砖从库存取出,装进刚开好的那个柜子。",
  },
  {
    id: "shipment",
    iconKey: "shipment",
    action: "封柜、离港",
    docName: "发运柜",
    role: "LOGISTICS",
    layer: "MAIN",
    band: "DELIVERY",
    inEdgeLabel: "柜装满了",
    tooltip: "柜子装满,封柜,然后确认离港。",
    what: "柜里的货够了就「封柜确认」,填上船名航次这些船务信息;然后确认离港,货正式发出。封柜要求柜里至少有一张已确认的出库单 —— 空柜不让封。",
    fromTo: "上一步:出库单把货装进了柜。下一步:离港后开始跟踪物流、办报关。在左侧菜单「仓储物流」→「发运柜」里操作(和开柜是同一个页面,只是柜到了封柜这一步)。",
    effect: "一旦封柜,柜里的出库单就冻住了 —— 不能改、不能撤、也不能再往里加新的。要动就得先撤封柜。封柜后确认离港,这一柜就发出去了。",
    narration: "柜子装满了,货代封柜、填船名航次,确认离港。",
  },
  {
    id: "logistics",
    iconKey: "logistics",
    action: "海运在途,跟到港口",
    docName: "物流跟踪",
    role: "LOGISTICS",
    layer: "MAIN",
    band: "DELIVERY",
    inEdgeLabel: "柜子上船了",
    tooltip: "在发运柜详情页里,按时间线登记途中的节点。",
    what: "柜子离港之后,一路上的节点(转运、到港等)按时间线登记进去,谁都能看到这柜货现在走到哪了。",
    fromTo: "上一步:柜子已确认离港。下一步:到港后办报关清关。**没有独立菜单** —— 在左侧菜单「仓储物流」→「发运柜」里点开某一票柜子,在详情页往下找物流时间线。",
    effect: "「到港」是终点,登记之后这柜的物流就到头了,不会再往后走。",
    narration: "船开了。货代一路把转运、到港这些节点登记进这个柜子的时间线。",
  },
  {
    id: "customs",
    iconKey: "customs",
    action: "报关清关",
    docName: "报关",
    role: "LOGISTICS",
    layer: "MAIN",
    band: "DELIVERY",
    inEdgeLabel: "货到目的港",
    tooltip: "在发运柜详情页里登记报关单号、上传报关资料。",
    what: "登记这柜货的报关单号和随附资料。一个柜子同一时间只有一条有效的报关记录;填错了就作废重录,不是直接改掉 —— 这样能留下改过的痕迹。",
    fromTo: "上一步:柜子已离港/到港。下一步:走到财务收付款收尾。**没有独立菜单** —— 在左侧菜单「仓储物流」→「发运柜」里点开某一票柜子,在详情页里找报关。",
    effect: "没登记就是「未报关」,登记了就是「已申报」,海关放行后标「已放行」。这三个状态是系统按有没有记录自动算的,不用手动改。",
    narration: "到港后办报关,货代把报关单号和资料传进这柜的报关记录,海关放行。",
  },

  // ---------- 资金流支线 ----------
  {
    id: "receivable",
    iconKey: "receivable",
    action: "客户欠我们钱",
    docName: "应收款",
    role: "FINANCE",
    layer: "MONEY",
    anchorId: "outbound",
    inEdgeLabel: "货一发出,客户开始欠钱",
    tooltip: "确认出库时自动产生,不用手工建。",
    what: "货发出去的那一刻,系统自动记一笔「客户欠我们多少钱」。注意它是自动产生的,不是财务手工建的单。",
    fromTo: "上一步:确认出库。下一步:客户打款后登记收款单来冲抵。在左侧菜单「财务」→「应收款」里查看。",
    effect: "应收款的状态(未收 / 部分收 / 已收清)是按已经收到多少自动算的,不用手动改。",
    narration: "货一发出,系统自动记下客户欠我们这笔货款。",
  },
  {
    id: "receipt",
    iconKey: "receipt",
    action: "收到客户货款",
    docName: "收款单",
    role: "FINANCE",
    layer: "MONEY",
    anchorId: "receivable",
    inEdgeLabel: "客户打款",
    tooltip: "登记客户实际打进来的钱,再核销到具体应收上。",
    what: "客户打钱进来,财务登记一张收款单,然后把这笔钱「核销」到具体哪几笔应收款上。一笔钱可以分着冲抵好几笔应收。",
    fromTo: "上一步:有没收清的应收款。下一步:这一单的钱就走完了。在左侧菜单「财务」→「收款单」里操作。",
    effect: "核销之后,对应应收款的余额自动减少,状态自动跟着变。核错了可以反核销退回去。",
    narration: "客户打款过来,财务登记收款单并核销到这笔应收上。",
  },
  {
    id: "payable",
    iconKey: "payable",
    action: "我们欠供应商钱",
    docName: "应付款",
    role: "FINANCE",
    layer: "MONEY",
    anchorId: "inbound",
    inEdgeLabel: "创建入库单时生成",
    tooltip: "供应商发货/我方拉货并创建入库单时自动产生。",
    what: "创建入库单的那一刻,系统自动记一笔「我们欠供应商多少钱」。和应收一样,是自动产生的。",
    fromTo: "上一步:创建入库单。下一步:付款后登记付款单来冲抵。在左侧菜单「财务」→「应付款」里查看。",
    effect: "应付款的状态(未付 / 部分付 / 已付清)按已经付了多少自动算。",
    narration: "瓷砖厂发货并创建入库单时,系统记下我们欠瓷砖厂的货款。",
  },
  {
    id: "payment",
    iconKey: "payment",
    action: "付款给供应商",
    docName: "付款单",
    role: "FINANCE",
    layer: "MONEY",
    anchorId: "payable",
    inEdgeLabel: "我们打款",
    tooltip: "登记实际付出去的钱,再核销到具体应付上。",
    what: "财务付钱给供应商,登记一张付款单,再核销到具体哪几笔应付款上。做法和收款单完全一样。",
    fromTo: "上一步:有没付清的应付款。下一步:这一单从头到尾彻底结清。在左侧菜单「财务」→「付款单」里操作。",
    effect: "核销后未结应付自动减少。同样支持反核销纠错。",
    narration: "财务付款给瓷砖厂并核销 —— 这一单从头到尾彻底结清。",
  },
];

/** 「跟一单货走一遍」的节点顺序:主链 10 步,穿插资金流在其自然发生的位置。 */
export const TOUR_SEQUENCE: string[] = [
  "quotation",
  "salesOrder",
  "purchaseOrder",
  "inbound",
  "inboundReceive",
  "payable",
  "shipmentOpen",
  "outbound",
  "receivable",
  "shipment",
  "logistics",
  "customs",
  "receipt",
  "payment",
];

/** 角色筛选选项:从 ROLE_META 派生,不手写。ADMIN 不触业务,不进筛选器。 */
export const GUIDE_ROLE_OPTIONS = (Object.keys(ROLE_META) as GuideRole[])
  .filter((code) => code !== "ADMIN")
  .map((code) => ({ value: code, label: ROLE_META[code] }));

export function guideNodeById(id: string): GuideNode | undefined {
  return GUIDE_NODES.find((n) => n.id === id);
}

/**
 * 语义域图例(顺序即图例展示顺序)。`colorToken` 是 `@/lib/tokens` colors 的键名——
 * 组件层用 `colors[colorToken]` 取值,数据层不 import 颜色,保持无 UI 依赖。
 */
export const GUIDE_CATEGORY_META: {
  id: GuideCategory;
  label: string;
  colorToken: "brand" | "info" | "brandAccent" | "muted";
}[] = [
  { id: "DOCUMENT", label: "业务单据", colorToken: "brand" },
  { id: "GOODS", label: "货 · 实物", colorToken: "info" },
  { id: "MONEY", label: "钱 · 财务", colorToken: "brandAccent" },
  { id: "MASTER_DATA", label: "基础资料", colorToken: "muted" },
];

/** 主链里「还没有实物、纯纸面」的单据节点。其余主链节点都在处理实物 = 货。 */
const DOCUMENT_MAIN_IDS = new Set(["quotation", "salesOrder", "purchaseOrder"]);

/**
 * 节点语义域派生(单一口径,不给每个节点塞字段):
 * 主数据层=基础资料;资金流层=钱;主链里报价/销售单/采购单=纸面单据,
 * 其余(入库/库存/出库/开柜/封柜离港/物流/报关)都在流转实物 = 货。
 * 分界=实物是否已存在:入库前无实物走单据,入库起有实物走货。
 */
export function nodeCategory(node: GuideNode): GuideCategory {
  if (node.layer === "MASTER") return "MASTER_DATA";
  if (node.layer === "MONEY") return "MONEY";
  if (DOCUMENT_MAIN_IDS.has(node.id)) return "DOCUMENT";
  return "GOODS";
}
