# buildreach-fulfillment

公司内部供应链履约系统 · 独立仓库(认证 / RBAC / 审计 / 存储底座 + 业务领域)。面向公司内部运营/采购/财务(**买方看不到**),与前台电商平台完全独立。

独立仓库、独立数据库、独立部署,不依赖任何外部主仓库。

## 进度

- **M0(已完成)**:工程基座——认证/JWT、RBAC(配置镜像 + 启动同步)、审计日志、Trace ID、附件存储薄接口、6 张基表 + 迁移。
- **M1(核心竖切,已完成)**:一条数据端到端——导入分类 → 种规格模板 → 建 SPU/SKU(i18n 形状 + JSONB 规格 + 中性编码)→ pg_trgm 搜索 → 录一张带规格快照的报价草稿。
  - 新模块:分类(只读导入)、分类规格建议模板、客户(最小档)、SPU/SKU、SKU 搜索、报价草稿。
  - 统一编号服务(`number_sequences` 表 + `allocate`):主数据全局号段 `SKU00000042`/`C000042`/`SPU00000042`,单据按年月号段 `Q2026070001`。
  - **不在 M1**:报价锁档/转销售/导出、采购/入库/库存/发货、各模块管理后台、翻译内容(内容纯中文,i18n 仅形状先行)。
- **商品管理做完整(已完成,分支 `feat/product-management`)**:M1 遗留的目录能力补齐。
  - **RBAC 细分**:权限点 `product:read`/`product:manage`(商品 SPU/SKU;`category:*`/`unit:*` 预留给将来
    品类树/单位维护写端点,职责分离),新增角色 `PRODUCT_OPERATOR`(商品运营,持 read+manage);`ADMIN`
    只保留 `product:read` 作职责分离过渡桥,不再持 `product:manage`(商品增改上下架收口给 `PRODUCT_OPERATOR`)。
  - **SPU 中性编码**:`spus.spu_code`(`SPU00000042`,复用统一编号服务)。
  - **创建人归属**:`spus`/`skus` 加 `created_by`(FK→users,NOT NULL,建索引),记商品运营录入归属,
    供"展示创建人/筛我的/按人统计录入量";非红线,`SpuOut`/`SkuOut` 下发。审计归属约定见 `app/db/base.py`。
  - **逻辑删**:`spus`/`skus` 都加 `deleted_at`,物理行永不删,读路径默认过滤已删;`DELETE` 端点即置
    `deleted_at`。
  - **商品状态机(三态生命周期)**:SPU `status` = `DRAFT`(草稿,新建默认)→ `ACTIVE`(启用)⇄ `INACTIVE`
    (停用);SKU 仍二态 `ACTIVE`/`INACTIVE`。语义 = **能否被下游(报价)选用**,非对外可见(内部平台无前台)。
    转移白名单 / 可编辑集(`EDITABLE=DRAFT,INACTIVE`)/ 可删集三张表放 model 层单一源头
    (`app/db/models/spu.py::SpuStatus`),service 每个写入口守卫,前端镜像成按钮显隐(`lib/productStatus.ts`)。
    - **ACTIVE 锁编辑/删除**:启用中的 SPU 及其 SKU 增改删一律拒(`ProductNotEditableError` 409),先停用再改。
    - **启用完备性**:`→ACTIVE` 须至少一个在售 SKU,否则拒(`ProductIncompleteError`)。不卡参考价 ——
      `reference_price` 是内部采购参考价(红线成本),报价成交价销售自填,可报价性不依赖它。
    - **SKU 上下架豁免**:启用中商品下仍可停售单个缺货变体;停用最后一个在售 SKU → 联动把 SPU 置 INACTIVE。
  - **派生可用性**:“可用”不落表——`SKU 可用 ⟺ 自身 ACTIVE ∧ 未删 ∧ 所属 SPU ACTIVE ∧ 未删`
    (`app/services/sku_service.py::sku_available`)。`GET /api/v1/skus?available=1` 按此过滤,供报价选货只看真正能卖的货。
  - **成本脱敏**:`skus.reference_price`(内部采购参考价)只有持 `product:manage` 的调用方能看到,否则序列化时
    置 `None`(`sku_out(..., include_cost=...)`)。
  - **商品图片**:`spus.main_image`(必填,创建校验 trim 后非空)/ `spus.images`(相册),`skus.image`
    (可选,回退 `spu.main_image`)。存储复用扩展后的 `Storage` 协议新增 `build_url`(展示 URL,OSS 可带
    `size` 走 `x-oss-process` 缩略)/ `create_upload`(前端直传描述);上传端点 `POST /api/v1/uploads`
    生成 `{key, upload_url, method}`,`STORAGE_BACKEND=local` 时另有 `PUT /api/v1/uploads/{key}` 本地接收
    ——key 形状强校验(`img/<uuid32>_<安全文件名>`)防路径穿越/越权覆盖,`content_type` 收窄到
    `jpeg/png/webp/gif`(显式排除 `image/svg+xml`,防存储型 XSS)。两个上传端点均守 `product:manage`。
  - **规格属性正规化**:`category_spec_attributes`(一属性一行,`UNIQUE(category_code,key)` + 4 个 CHECK,
    `value_type`/`options⇔enum`);运营 inline 新增属性/enum 选项由后端生成随机稳定 key(`a_`/`v_` + base62),
    中文只进 `label_i18n`,绝不进 key 列(身份≠展示)。
  - **规格属性按产品族继承**:属性按"通用挂大类、特有挂子类"落在其适用的最高分类层;叶子建 SKU 时
    `get_suggestions` 沿点分祖先链把整条链的属性**并集**返回(同 key 深覆浅,子类可覆盖父类),对齐
    PIM/ERP 的分类-属性继承(Akeneo family / SAP class)。inline 新增 enum 选项写回属性**归属层**(可能是祖先),
    对该层所有后代叶子共享。属性种子唯一源头 = `app/seed_data/spec_attributes.json`(`app/seed.py::seed_spec_templates`
    读取,幂等 upsert;分类未导入则对应条目跳过,导入后重跑补齐)。首批覆盖金属管道/塑胶管道/紧固件/电线电缆。
  - **SPU/SKU 规格分层(scope)**:`category_spec_attributes.scope`(`spu` 产品级 / `sku` 变体轴,挂在
    (category_code,key) 行,同 key 跨品类可不同、同继承链须一致)。产品级值住 `spus.spec_jsonb`(SPU 填一次),
    变体轴住 `skus.spec_jsonb`;**键不重叠、读时并集**(`spec_display` 后端单一解析,详情/报价共用)。写入按 scope
    守卫(投错门 400);SPU 有规格或子 SKU 时**改分类锁定**(409)。对齐 Akeneo common/axis、管家婆属性组合。
  - **两层搜索**:`spus.search_text`(名+品牌+产品级规格,pg_trgm)找**商品**,`list_spus` 关键词走它;
    `skus.search_text` = SPU 名/品牌/产品级规格 ∪ SKU 名/轴 + code(denormalize,找**变体**,供后续报价选货)。
    SPU 名/品牌/产品级规格变更级联重算子 SKU search_text。enum 值解析成 label 入索引(搜中文材质词命中)。
  - **售卖单位专表**:`units`(`code` 做 PK + `label_i18n`,主数据独立迁移),`skus.unit` 收编为 FK
    `units.code`(`ON DELETE RESTRICT`);单位种子唯一源头 = `app/seed.py::seed_units`。
  - **品类子树过滤**:`GET /api/v1/spus?category_code=...&include_descendants=1` 走 `text_pattern_ops` 前缀索引。
  - **已知限制**:SPU 列表关键词只匹配中文名 + `spu_code`(SKU 搜索走 `search_text` 覆盖全语言)。
    (local 图片预览已由前端落地时新增的 `GET /media/{key}` 补齐,见下方商品管理前端条目。)
  - **迁移(开发初期净片)**:因未上线,商品目录迁移已合入终态、删除补丁链——`0003_spec_attributes`
    (规格属性正规化)、`0006_units`(单位专表)、`0007_spu_sku`(SPU/SKU 一次建成:编码/软删/图片/单位 FK/
    双索引/CHECK)。旧 `0008–0012` 补丁迁移已废除。**重建库**:改历史后 dev/test 库需 `dropdb && createdb`
    重跑 `alembic upgrade head`(无历史数据,不做在线迁移)。

- **商品管理前端 + 图片建模(已完成,分支 `feat/product-management-fe`)**:消费 catalog API 的运营界面 + 商品图规范化。
  - **组件地基**:Ant Design(`ConfigProvider` 主题令牌对齐 `frontend/DESIGN.md`,主色 `#003366`)+ 现有
    Zustand authStore / RouteGuard;`AppShell`(暗色侧栏 + 顶栏 + 面包屑)。设计**唯一源头 = `frontend/DESIGN.md`**。
  - **页面**(`/catalog`,守 `product:read`):SPU 列表(分类树子树过滤 / 关键词 / 状态 / 无可用 SKU 徽标)、
    SPU 详情(封面 + 图集 + 内嵌 SKU 列表 + 派生可售)、SPU 增改抽屉、SKU 增改抽屉(**模板驱动规格
    编辑器**:enum→下拉+新增选项逃生口 / number→带模板单位后缀 / string;售卖单位取自 `/units`)、SKU 全局搜索。
  - **商品图规范化(`product_images` 表)**:一图一行,`image_type` **MAIN/GALLERY/DETAIL** + `sku_id` 区分层级
    (对齐 buildreach)。封面=SPU 级唯一 MAIN 行(**部分唯一索引**硬保证);写接口按 `image_key` 对账(reconcile,
    换封面先降后升防撞唯一索引);身份键 `UNIQUE(spu_id,image_key)` 硬约束。删旧 `spus.main_image/images`、`skus.image`。
  - **图片管理器(前端)**:`ImageZone`/`SpuImageManager` —— 主图/轮播区(≤6,拖拽排序,☆ 切换封面,第一张为封面)
    + 详情图区(≤12)+ SKU 图(≤6,不绑轴);单图 ≤20MB(前后端硬限);两步直传 `POST /uploads` → PUT,一套代码兼容
    OSS 直传与 local PUT,表单只存 object key。
  - **权限显隐**:`<Can perm="product:manage">` 控新建/编辑/上下架/删除/参考价/图片;后端 `require_permission` +
    `reference_price` 脱敏是安全底线,前端只是 UX 层。**ADMIN 只读**、**PRODUCT_OPERATOR 全权**。
  - **本地图片预览**:后端 `GET /media/{key}`(**仅 `STORAGE_BACKEND=local`**,key 形状白名单、公开读)补齐
    `LocalDiskStorage.build_url` 的服务端点——local dev 上传图现可预览(生产走 S3/OSS 公读桶,不经本端点)。

- **报价(主流程第一步,已完成,分支 `feat/quotation-increment`)**:客户销售报价单,SKU 维度整单增改 + 生命周期。
  - **状态机(四态)**:`DRAFT`(草稿,可编辑可硬删)→ `LOCKED`(锁档,冻结基准,手动)→ `CONVERTED`(已转销售,终态)/
    `VOID`(已作废,终态);`LOCKED` 可撤回回 `DRAFT`。转移白名单 / 可编辑集 / 可删集 / 可作废集四张表放 model 层
    单一源头(`app/db/models/quotation.py::QuotationStatus`),service 每写入口 `_assert_transition` 守卫,
    前端镜像成按钮显隐(`lib/quotationStatus.ts`)。语义=能否被下游〈转销售〉选用,非对外可见。
  - **整单保存**:`PUT /quotations/{id}` 一次提交表头 + 全部行,行按 `id` 对账(有 id→UPDATE、载入后不在 payload→DELETE、
    无 id→INSERT);`total_amount` 由行反规范化维护(行是源);乐观锁 `expected_updated_at` 不匹配 → 409 `edit_conflict`。
  - **规格快照**:下单那刻冻结展示串(名/规格/单位)入行,不随主数据变;规格文本 = SPU 产品级 ∪ SKU 轴级并集
    (`compose_line_snapshot`,对齐 PR9 规格分层)。选货只收「可选货」(SKU 与 SPU 均 ACTIVE 未删,`assert_sku_available`)。
  - **报价人可改派**:`salesperson_id`(FK→users,`ON DELETE RESTRICT`,NOT NULL,默认=建单人),可改派给其他持
    `quote:manage` 的人;`GET /users/selectable` 供下拉。摘要 `summary`(≤180)/ 表头备注 / 行备注均选填。
  - **RBAC**:新增角色 `SALES`(销售,持 `quote:manage`+`customer:read`+`product:read`);`quote:manage` 从 `ADMIN`
    移除(ADMIN 严格不碰业务数据);客户列表读放宽为 `require_any_permission(customer:read, customer:manage)`。
  - **8 端点**(均守 `quote:manage`):`GET /quotations`(筛选/排序/分页)、`POST`、`GET/{id}`、`PUT/{id}`、`DELETE/{id}`
    (仅草稿硬删)、`POST/{id}/lock`、`/unlock`、`/void`。单号走 `NumberScope.QUOTATION`(`Q{YYYYMM}####`,模块段 MM=14)。
  - **前端**(`/sales/quotations`,守 `quote:manage`):列表(状态 Segmented / 关键词 / 报价人=我 / 总额排序 / 行点击进详情 /
    行内编辑作废删除)、详情(Descriptions + 明细表 + 状态门禁 锁档/撤回/作废/编辑 + 返回箭头)、整单编辑器(new 与
    edit?edit=1 共用;表头 2 列网格,明细含 规格/单位 只读派生列 + 数量/单价/金额,合计实时算)。选货走**右侧挑货抽屉**
    `ProductPickerDrawer`(复用 catalog SKU 搜索 available=true,缩略图 + 名/码/单位,连加多件、已加标记)。菜单按权限
    显隐加「报价管理」。迁移 `0014_quotation_lifecycle`。

- **转销售(主流程第二步,已完成,分支 `feat/convert-to-sales`)**:锁档报价 → 销售单。**整单转 1:1、销售单自持冻结行**。
  - **范式**:分离文档 + 下游反向 FK(对齐 SAP SD document flow / NetSuite `createdFrom`;非 Odoo 同记录换态,因下游
    采购/发运/财务单挂销售单,销售单须是独立生命周期文档)。`sales_orders.source_quotation_id → quotation_orders.id`
    (`ON DELETE RESTRICT`,**UNIQUE**),报价不加前向列,反查靠 `WHERE source_quotation_id=:qid`。
  - **转换语义**:`POST /quotations/{id}/convert`(守 `quote:manage`,与 lock/void 同族的报价终态转移)。单事务原子:
    悲观锁读报价 → 精确守卫 `status==LOCKED` 否则 `409` `cannot_convert`(模块段 **41409**)→ 建销售单 + **平移**报价行
    已冻结快照(不重算)→ 报价 `LOCKED→CONVERTED`(终态,撤不回、不重复转)。`UNIQUE(source_quotation_id)` +
    `UNIQUE(source_quotation_line_id)` 在最强层硬保证「一报价≤一销售单、每报价行只入单一次」(并发/复制 bug 兜底)。
  - **审计两行**:`CREATE`/`sales_order`(销售单诞生)+ `CONVERT`/`quotation`(报价转移),与全库「每实体审计自己 CREATE」一致。
  - **销售单表**:`sales_orders`(复制 customer/salesperson/lang/currency/total/summary/remark;初始态 `CONFIRMED`,
    完整 SO 状态机留给转采购)+ `sales_order_lines`(平移六个快照列 + `source_quotation_line_id`)。行 write-once →
    `TimestampMixin`(仅 `created_at`),与草稿期可变的 `QuotationLine`(`TimestampUpdateMixin`)按真实可变性分叉。
  - **RBAC**:新增权限点 `sales:read`(销售单读),加到复用的 `SALES` 角色;convert 复用 `quote:manage`,不造 `sales:manage`
    (本增量销售单无独立写面)。销售单本阶段只承载对客成交价,**无红线字段**(采购价/供应商在采购步才出现)。
  - **端点**:`POST /quotations/{id}/convert`(守 `quote:manage`)、`GET /sales-orders`(筛选/排序/分页)、`GET /sales-orders/{id}`
    (含行 + 来源报价号,守 `sales:read`);报价详情增补 `order.sales_order?:{id,no}`(反查出口)。单号走
    `NumberScope.SALES_ORDER`(`SO{YYYYMM}####`)。
  - **前端**(`/sales/orders`,守 `sales:read`):列表(状态 / 报价人=我 / 总额排序 / 行点击进详情)、详情(只读:头部含
    来源报价链接 + 明细表)。报价详情页加「转销售单」危险确认动作(锁档态)+「查看销售单」出口(已转态)。菜单按
    `sales:read` 显隐加「销售单」;`/sales` 段权限下沉到 quotations/orders 各自 layout。迁移 `0016_sales_order`。

- **采购(主流程第三步,分支 `feat/purchase-order`)**:**按单采购**——基于某张 `CONFIRMED` 销售单(SO)独立发起采购单(PO),
  **无「转」语义**(SO 自身状态不变,只被约束 SKU 范围与数量上限)。参照 SAP MM / Odoo Purchase / NetSuite 共性。
  - **两条正交轴**:轴1 单据生命周期(人驱动管门禁)PO `DRAFT→CONFIRMED→CANCELLED`(草稿可编辑/硬删,已确认锁定只能取消,
    不设 SENT/RECEIVED——到货留入库步);轴2 流程进度(机器派生)SO 的 `purchase_progress`(未/部分/已全部下单)**不落列、
    不进 SO 主状态机**,列表 JOIN 派生(方案B)。**SO 表本步零改动**。
  - **SO:PO = 1:N**(按供应商拆单):`purchase_orders.source_sales_order_id`(FK RESTRICT,index,**不 UNIQUE**);PO 行
    `source_sales_order_line_id`(FK RESTRICT,**不单列 UNIQUE**,入复合 `UNIQUE(purchase_order_id, source_sales_order_line_id)`
    = PO 内唯一,跨 PO 允许分批/换供应商/取消重下)。
  - **超采守卫(单一口径)**:`compute_covered_qty`(SO 行 covered = Σ 非 CANCELLED PO 行 qty,**含 DRAFT**)被守卫/列表进度/
    详情三处共用;`assert_within_so_line_quota` 同事务内 `SELECT ... FOR UPDATE` 锁 SO 行再读聚合再写入(并发双草稿不能合计超额,
    否则 `41603`)。金额走 `Decimal(str())` 精度(镜像报价)。
  - **红线(全仓首个字段级脱敏)**:采购价 `unit_price` / 行额 `line_total` / 单头金额 `total_amount` = 成本红线,对无
    `purchase:read_cost` 者**后端置 null**(非仅前端隐藏)。脱敏下沉到响应 schema 构造工厂(`schemas/purchase_order.py` 的
    `*.build(..., can_see_cost=)` 单点经 `rbac/redaction.py::redact_cost`),覆盖列表/详情行/SO 关联 PO 区三处出口。供应商身份
    是另一条红线,由端点级 `purchase:read` 门控(SO 详情 `related_purchase_orders` 仅 `purchase:read` 者下发)。
  - **主数据**:`suppliers`(独立表,照 customers 档次 + `default_currency` + 启停 toggle;号 `NumberScope.SUPPLIER`=`V######`)。
  - **RBAC**:新增角色 `PURCHASER`(采购员),权限点 `supplier:manage/read` + `purchase:manage/read` + `purchase:read_cost`
    (红线开关,独立拆出为入库步预埋轴)+ 复用 `sales:read`(发起采购读 SO)+ `product:read`。审计加 `CONFIRM`/`CANCEL`/
    `ACTIVATE`/`DEACTIVATE` 动作 + `supplier`/`purchase_order` 资源类型。
  - **端点**:供应商 CRUD + `activate`/`deactivate`(守 `supplier:*`);采购单 `POST /purchase-orders`、列表/详情、`PUT`(整单对账+乐观锁,
    仅草稿)、`DELETE`、`confirm`、`cancel`(守 `purchase:*`)、`GET /purchase-orders/purchasable-lines`(建单器数据源:剩余额度 +
    建议价);SO 列表增补 `purchase_progress` 徽标 + 筛选,SO 详情增补每行 `covered_qty` + 进度徽标 + 关联 PO 区。单号
    `NumberScope.PURCHASE_ORDER`(`PO{YYYYMM}####`)。错误码段 15(供应商 `415xx`)/ 16(采购单 `416xx`)。
  - **前端**(`/purchasing/{suppliers,orders}`):供应商列表/详情/表单(启停);采购单列表 / 详情(状态门禁动作)/ 建单器(SO 详情
    「发起采购」入口→选供应商→可采行录量价→建草稿 PO);SO 详情/列表采购进度扩展。金额列为红线:对无 `purchase:read_cost` 者后端置
    null、前端显「—」(当前 `PURCHASER` 全看,此脱敏为入库仓库角色预埋)。迁移 `0017_supplier` + `0018_purchase_order`。

- **入库 + 应付款骨架(主流程第四步,分支 `feat/inbound-order`)**:入库单(ASN)= 把「订货承诺」变成「实收事实」;
  基于某张 `CONFIRMED` 采购单(PO)分批到货登记。参照 SAP/Oracle/NetSuite 共性:PO → GR(收货)→ IR(发票),
  **应付随收货成立**(非采购确认)。
  - **状态机(两态 + 作废,无草稿)**:`IN_TRANSIT→{RECEIVED,CANCELLED}`、`RECEIVED→IN_TRANSIT`(撤销入库,守卫式纠错口);
    建单事件=供应商已发货,在途本身即可编辑工作态。无硬删(对应真实发货事件)。收货进度轴2(机器派生)PO 的
    `receipt_progress`(未/部分/全部收,**仅 RECEIVED 计入**)**不落列**,列表/详情 JOIN 派生。PO 状态机本步零改动,
    仅加取消守卫:CONFIRMED→CANCELLED 需**无活动入库单**(`IN_TRANSIT`/`RECEIVED`),否则 `41609`。
  - **1 PO : N 入库单**(分批到货):`inbound_orders.purchase_order_id`(FK RESTRICT,index,**不 UNIQUE**);入库行
    `purchase_order_line_id`(FK RESTRICT,入复合 `UNIQUE(inbound_order_id, purchase_order_line_id)`= 单内唯一,跨单允许分批)。
  - **超收守卫(单一口径)**:`compute_inbounded_qty`(Σ 非 CANCELLED 入库行 qty,**含在途**=守卫口径)/ `compute_received_qty`
    (Σ 仅 RECEIVED=进度/库存口径)函数族守卫/进度/可收行三处共用;`assert_within_po_line_quota` 同事务 `FOR UPDATE` 锁 PO 行,
    超收 `41703`。建单/确认先锁 PO 头校 `CONFIRMED`,与 PO 取消并发闭环锁序统一(PO 头→PO 行)。
  - **零成本入库单据(红线面最小化)**:入库单/行**不落任何价格/金额列**(契约 D3),入库 UI 对无成本权限者天然无红线字段;
    应付金额在确认入库事务内读 PO 行价(逐行 `quantize` 2dp 再求和)计算,只落 `payables`。详情内嵌 PO 摘要走既有
    `PurchaseOrderOut.build(can_see_cost=)` 脱敏。
  - **应付款账层(财务域全局表,独立迁移 `0020_payable`)**:粒度 = **每张入库单一张**;幂等键 = 活动行偏唯一
    `UNIQUE(inbound_order_id) WHERE voided_at IS NULL`(重复确认不生第二张;撤销入库作废后可重收)。`balance` = **本仓首个生成列**
    `GENERATED ALWAYS AS (amount_original - amount_allocated) STORED`(恒等式落 DB 最强层)。`amount_original` 创建即定死;
    `status`(未付/部分付/已付清)完全派生不落列。撤销入库同事务 **void payable**(置 `voided_at/by/reason`,行留痕不硬删);
    所有余额/列表聚合 `WHERE voided_at IS NULL`。payments/allocations/receivables + 发票接入 = 财务步。
  - **RBAC**:权限点 `inbound:manage`/`inbound:read`(入库单据零成本,无 `read_cost` 轴)+ `payable:read`(🔴 应付整域端点级门控);
    P0 由 `PURCHASER` 兼收货(WAREHOUSE 角色触发式后置)。审计加 `RECEIVE`/`UNRECEIVE` 动作 + `inbound_order`/`payable` 资源类型。
  - **端点**:入库单 `POST /inbound-orders`、列表/详情、`PUT`(仅在途整单重写)、`receive`/`unreceive`/`cancel`、
    `GET /inbound-orders/receivable-lines`(建单器数据源);`GET /payables`(🔴 `payable:read`);PO 列表/详情增补
    `receipt_progress` 徽标 + 行级在途/已入 + 入库记录区。单号 `NumberScope.INBOUND`(`IN{YYYYMM}####`);应付账层无业务号。
    错误码段 17(入库/应付 `417xx`)+ PO 取消守卫 `41609`。
  - **前端**(`/inbound` + `/finance/payables`):入库列表/详情(状态门禁动作:确认入库/撤销入库/作废)/ 建单抽屉
    (选 CONFIRMED PO→可收行录量→在途/已入/剩余镜像 quota);PO 详情/列表收货进度扩展;应付款极简列表(🔴 `payable:read`)。
    入库单据前端零成本列。迁移 `0019_inbound_order` + `0020_payable`。

## 本地开发

本地开发**复用现有 brew PostgreSQL**(`@ :5433`),不用下面 `docker-compose.yml` 里的 `db` 服务
——`docker-compose.yml` 的 `db` 只供整机部署/演示用。

### 1. 建库(一次性)

```bash
psql -h localhost -p 5433 -c "CREATE DATABASE fulfillment_dev;"
psql -h localhost -p 5433 -c "CREATE DATABASE fulfillment_test;"
```

### 2. 后端

```bash
cd backend
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# .env(不提交,见根目录 .env.example)
cp ../.env.example .env
# 至少改: DATABASE_URL 指向 fulfillment_dev、JWT_SECRET_KEY(任意 >=16 字符)

alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

启动时会自动跑幂等 seed:种入 `SUPER_ADMIN_EMAIL`/`SUPER_ADMIN_INITIAL_PASSWORD` 指定的管理员账号
(首次登录强制改密)、同步 RBAC 权限点。

对象存储默认 `STORAGE_BACKEND=local`(写入 `backend/private_uploads/attachments`),不需要额外起
MinIO。要在本地验证 S3/MinIO 路径,单独起一个 MinIO 容器并把 `STORAGE_BACKEND` 切成 `s3`
(见 `.env.example` 里注释的 `S3_*` 项)即可,不需要整套 `docker compose up`。商品图(`main_image`/
`images`/`sku.image`)与附件共用同一套 `Storage`(`local` 落同一目录,`s3` 即生产 aliyun OSS),没有
独立的新环境变量。

### 3. 前端

```bash
cd frontend
pnpm install   # 含 Ant Design(antd / @ant-design/nextjs-registry / @ant-design/icons)+ dayjs(DatePicker 所需)
echo 'NEXT_PUBLIC_API_BASE_URL=http://localhost:8000' > .env.local   # 浏览器直连后端,必须 NEXT_PUBLIC_ 前缀
pnpm dev
```

访问 `http://localhost:3000`(登录后自动进商品目录操作台 `/catalog/spus`,需持 `product:read` 的账号)。

**前端环境变量**(`.env.local` 或容器注入 `window.__ENV`):

| 变量 | 说明 |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | 后端公网地址(**必填**;登录/接口在浏览器侧发起,故须 `NEXT_PUBLIC_` 前缀才注入 bundle。SSR 亦读 `API_BASE_URL`) |
| `NEXT_PUBLIC_IMAGE_BACKEND` | `local`(默认,经后端 `/media` 读)/ `s3`(公读桶直读) |
| `NEXT_PUBLIC_IMAGE_PUBLIC_BASE` | `s3` 时的公读桶基址(如 `https://cdn.example.com`) |

**账号**:启动 seed 只种 `SUPER_ADMIN_*` 的 **ADMIN**(对商品**只读**)。商品增改需 **PRODUCT_OPERATOR**
角色的账号 —— 生产由 ADMIN 经用户/角色管理授予;本地 QA 走一次性脚本(先启动过一次后端让 rbac 同步建好角色):

```bash
cd backend && source .venv/bin/activate
python -m scripts.create_product_operator --email op@example.com --name 商品运营 --password 'Aa123456789'
```

设计基准见 `frontend/DESIGN.md`。

## 测试

```bash
cd backend
source .venv/bin/activate
pytest -v
```

默认连 `fulfillment_test`(可用 `TEST_DATABASE_URL` 覆盖),与开发库 `fulfillment_dev` 隔离。
CI(`.github/workflows/ci.yml`)跑同一套 `pytest` + `alembic upgrade head`(用一次性 PG 16 容器)。

> 测试 schema 走 `Base.metadata.create_all`(非 alembic)+ SAVEPOINT 逐测隔离。故裸 DDL(pg_trgm
> 扩展、`number_sequences` 号段表)必须两条建表路径都就绪:迁移里显式建 + `Base.metadata` 的
> `before_create` 事件建。

### pg_trgm 扩展(SKU 搜索依赖)

SKU `search_text` 的 GIN 索引依赖 `pg_trgm`。迁移 `0002` 会 `CREATE EXTENSION IF NOT EXISTS pg_trgm`,
`app/db/base.py` 也注册了 `before_create` DDL(供测试 `create_all` 路径)。**生产 DB 角色需具备建扩展
权限,或由 DBA 预建。**

## 分类导入(一次性脚本,非产品功能)

前台 `categories`(zh/en/sw 三列)→ 履约 `categories`(`name_i18n` JSONB),保留
`code`/`parent_code`/`level`/`is_leaf`/`sort_order`。

```bash
cd backend
# 先 dry-run 用真实数据验证(不落库),确认无误再去掉 --dry-run 正式导入
.venv/bin/python -m scripts.import_categories --file scripts/<前台导出>.json --dry-run
.venv/bin/python -m scripts.import_categories --file scripts/<前台导出>.json
```

JSON 形状见 `scripts/sample_categories.json`。幂等:`code` 已存在则跳过;`name_i18n.zh` 缺失记 error 不插。
真实的 32 一级大类 + 子树由运营从前台导出后替换样例文件再导。

## 编号 / i18n 约定

- **编号**:业务号统一由编号服务发放,不拼主键;主数据中性不透明全局号段,单据按类型 + 年月号段;
  可变业务信息(客户/供应商/品类等)不进编号,作为独立字段查询。
- **i18n**:多语言是数据层的事,内部界面全程中文;文本走 `_i18n` JSONB(**zh 必填、禁空串**),读取统一
  过 `display(field, lang, fallback="zh")`(fallback 链 目标→en→zh);语言集合定死 **zh/en/sw**,内容
  纯中文、按需再补。

## 容器部署(整机部署/演示)

```bash
cp .env.example .env   # 改 JWT_SECRET_KEY / POSTGRES_PASSWORD / SUPER_ADMIN_* 等敏感项
docker compose --env-file .env up -d --build db minio backend
```

起 `db`(独立于本地开发用的 brew PG)+ `minio`(演示对象存储)+ `backend`(容器内自动等库就绪→
`alembic upgrade head`→启动,见 `backend/docker-entrypoint.sh`)。`minio` 里业务用的 bucket
(`fulfillment-attachments`)由 `minio-init` 一次性服务自动建好(幂等,随 `backend` 一起触发,不需要
单独跑);生产走 aliyun OSS 时 bucket 由运维预先建好,没有对应的一次性服务。

`frontend` 服务在 `docker-compose.yml` 里已占位,但**还没有 `frontend/Dockerfile`**(T7 只搭了本地
`pnpm dev` 开发壳,未做生产构建镜像)——补齐 Dockerfile 前,`docker compose up` 不带 service 名的全量
启动会在 frontend 这一步失败;跑 `db minio backend` 三件套即可验证后端全链路,前端仍用 `pnpm dev`
起本地开发模式连它。

单独验证后端镜像可构建:

```bash
docker compose build backend
```

## 待接

- GitHub remote 已建:`origin` → `github.com/matgo-dev/buildreach-fulfillment`。远端 CI
  (`.github/workflows/ci.yml`)已在 GitHub Actions 实跑:PR 触发 pytest + 前端 lint/build 卡点,当前绿。
  仍待接:远端部署编排(目前本仓库无对应目录,后续按需补)。
- `frontend/Dockerfile`:生产构建镜像待补(见上「容器部署」一节)。
- 前端界面:登录/改密壳 + 商品目录全套(SPU/SKU 列表·详情·增改)+ 报价全套(列表·详情·整单编辑器)
  已上;随主流程各步(转销售/采购/入库…)后端稳定后逐步补(内部界面,中文)。
