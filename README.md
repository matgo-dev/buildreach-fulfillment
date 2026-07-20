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
    (`ON DELETE RESTRICT`,**活动行偏唯一**,见下方取消增量),报价不加前向列,反查靠
    `WHERE source_quotation_id=:qid AND status<>'CANCELLED'`。
  - **转换语义**:`POST /quotations/{id}/convert`(守 `quote:manage`,与 lock/void 同族的报价终态转移)。单事务原子:
    悲观锁读报价 → 精确守卫 `status==LOCKED` 否则 `409` `cannot_convert`(模块段 **41409**)→ 建销售单 + **平移**报价行
    已冻结快照(不重算)→ 报价 `LOCKED→CONVERTED`(SO 取消可回退,见下)。活动行偏唯一(`source_quotation_id
    WHERE status<>'CANCELLED'`)+ 复合 `UNIQUE(sales_order_id, source_quotation_line_id)` 在最强层硬保证
    「一报价≤一**活动**销售单、同单内每报价行只入一次」(并发/复制 bug 兜底;跨单放行支持取消后重转)。
  - **审计两行**:`CREATE`/`sales_order`(销售单诞生)+ `CONVERT`/`quotation`(报价转移),与全库「每实体审计自己 CREATE」一致。
  - **销售单表**:`sales_orders`(复制 customer/salesperson/lang/currency/total/summary/remark;初始态 `CONFIRMED`,
    完整 SO 状态机留给转采购)+ `sales_order_lines`(平移六个快照列 + `source_quotation_line_id`)。行 write-once →
    `TimestampMixin`(仅 `created_at`),与草稿期可变的 `QuotationLine`(`TimestampUpdateMixin`)按真实可变性分叉。
  - **RBAC**:权限点 `sales:read`(销售单读)+ `sales:manage`(SO 写面:取消;取消增量补),均仅 `SALES` 角色
    (ADMIN 按 Q25 不触业务)。销售单本阶段只承载对客成交价,**无红线字段**(采购价/供应商在采购步才出现)。
  - **端点**:`POST /quotations/{id}/convert`(守 `quote:manage`)、`GET /sales-orders`(筛选/排序/分页)、`GET /sales-orders/{id}`
    (含行 + 来源报价号,守 `sales:read`);报价详情增补 `order.sales_order?:{id,no}`(反查出口)。单号走
    `NumberScope.SALES_ORDER`(`SO{YYYYMM}####`)。
  - **前端**(`/sales/orders`,守 `sales:read`):列表(状态 / 报价人=我 / 总额排序 / 行点击进详情)、详情(只读:头部含
    来源报价链接 + 明细表)。报价详情页加「转销售单」危险确认动作(锁档态)+「查看销售单」出口(已转态)。菜单按
    `sales:read` 显隐加「销售单」;`/sales` 段权限下沉到 quotations/orders 各自 layout。迁移 `0016_sales_order`。
  - **SO 整单取消(回补增量,契约 `docs/契约/2026-07-16-0707`)**:`POST /sales-orders/{id}/cancel`(守 `sales:manage`,
    段 18:41801 非法转移 / 41802 存在活动 PO)。范式 = SAP/NetSuite/Odoo 共性:下游活动单据硬拦、**不级联**、解链
    人工自下而上。单事务:锁 SO 头 → 41802 守卫 → 置 `CANCELLED`(留痕 `cancelled_at/by/reason` + 一致性 CHECK)→
    报价 `CONVERTED→LOCKED` 回退可改可重转;审计两行 extra 互指(`CANCEL`/SO + `UNCONVERT`/报价)。配套收紧:公开
    lock 端点仅 DRAFT(41401);报价删行/删单被 SO 行引用 → 41411(改量/价放行);建 PO 锁 SO 头防 TOCTOU;
    `purchasable_only` 服务端排除 CANCELLED。前端:详情「取消销售单」危险确认(原因留痕)+ 已取消隐藏进度徽标与
    发起采购;列表加「已取消」tab。迁移 `0021_so_cancel`(downgrade 前提:无取消+重转数据)。

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

- **库存(主流程第五步,分支 `feat/inventory-increment`)**:订单履约跟踪 = 回答「每个销售单每个 SKU
  到货多少、已出多少、可发多少」。**B 方案:纯派生,零新表、零迁移**——货从采购起即唯一归属某销售单
  (`purchase_order_lines.source_sales_order_line_id` 是 Ownership 非 Reference,守卫链保证系统无自由库存),
  故四量由既有 FK 单据链 `inbound_order_lines → purchase_order_lines → sales_order_lines` 纯聚合派生,
  不记第二份「库存账」。对标管家婆/金蝶/好生意「订单执行跟踪」(全部单据链派生、无一记账)。
  - **单一口径 `compute_stock_balance`**(`services/stock_balance_service.py`,地位同 `compute_covered_qty`):
    全仓「在库/可发」唯一算法源头,库存页 / SO 详情库存块 / (出库步)锁内校验 / (将来物化)回填全部消费它。
    **防 join 放大**:同一 SO 行可拆多 PO、同一 PO 行可拆多入库单,三臂(订购/已入库/出库)各自预聚合再按
    `(sales_order_id, sku_id)` FULL JOIN 合并,`SUM` 不按分支翻倍。四量:`ordered_qty` / `inbound_qty`(仅
    `RECEIVED` 计入,在途不算)/ `outbound_qty`(本步恒 0,签名为出库步预留)/ `available_qty = inbound − outbound`。
    合并行展示字段(品名/规格串/单位)取 **SKU 当前档**(非行快照),按所属 SO 语言渲染。
  - **行包含 `scope`(一函数一参数,不许两套 SQL)**:`available`(默认,在库视角 `available>0`,已履约行退出,
    内容被货代仓容量钉死、不随经营年限增长)/ `history`(履约史 `inbound>0 OR outbound>0`)/ 内部 `all`
    (SO 详情块:该 SO 全部行含已入 0,对照订购)。
  - **RBAC**:新权限点 `inventory:read`(唯一,无 manage——库存无写入口)。授 **`PURCHASER` + `SALES`**;
    **`ADMIN` 不授**(Q25 职责分离,与 `sales:read`/`purchase:read` 一致)。无成本/供应商/金额字段 → **零红线、零脱敏分支**。
  - **端点**:`GET /api/v1/inventory`(守 `inventory:read`;分页 `Page[T]`,筛选 `sales_order_id`/`sku_id`/`q`
    (SO单号/SKU编码/品名)+ `scope`);**SO 详情响应加 `stock_balances` 块**——按调用者持 `inventory:read`
    **条件下发**(照 `related_purchase_orders` 按 `purchase:read` 下发的既有模式,响应键存在与否驱动前端,
    后端脱敏非前端隐藏)。无写端点(无手工调整/盘点)。
  - **性能冒烟**(`scripts/inventory_perf_smoke.py`,一次性库,手动跑 `python -m scripts.inventory_perf_smoke [N]`):
    10 万级 RECEIVED 入库行下,① 单 SO 派生路径全走 FK 索引 `EXPLAIN` 恒定 **0.6ms**(不随总量增长,出库锁内校验/
    SO 详情块的性能基线);② 全量默认口径(整表聚合 + top-N)**≈277ms**(远超可见的千级规模;可见规模为亚毫秒)。
    衰老方式=变慢(可见、有界),非变错——契约 §6.2 物化期权随时可行使,触发前不建。

- **出库 + 发运骨架 + 应收款(主流程第六步,分支 `feat/outbound-increment`)**:出库单 = **销售单 N:1 × 发运单(柜)N:1**
  的桥;行不跨 SO、不跨柜,一柜内每来源 SO 各一张。参照 SAP/NetSuite:两段式 `草稿 → 已出库`(无 WMS 拣货/复核中间态),
  **确认出库 = 唯一扣库存事件**(草稿不扣),可撤销恢复(装船前);**应收随发货成立**(与应付=收货完全对称)。
  - **状态机(model 层单一源头)**:出库单 `DRAFT→{ISSUED,CANCELLED}` / `ISSUED→{DRAFT}`(撤销出库);
    柜 `OPEN→{CANCELLED}`(订舱/装船态归发运步扩展)。偏唯一 `UNIQUE(shipment_id, sales_order_id) WHERE status<>'CANCELLED'`
    =「一柜内每来源 SO 各一张」落 DB;取消退出偏唯一可重开。
  - **库存 outbound 臂接入**:`compute_stock_balance` 第三臂 = `Σ(qty) FROM outbound_order_lines JOIN outbound_orders
    WHERE status='ISSUED' GROUP BY (sales_order_id, sku_id)`,`available = 入库 − 出库`(草稿不计,撤销回 DRAFT 自然恢复)。
    锁内校验/穿仓守卫经 `available_by_sku()` **复用同一 `_balance_subquery`**(单一口径,不另写聚合)。
  - **并发 = 悲观锁(收紧型写入口仅两处,同锁序 `SO 头 → 出库单头`)**:① 确认出库:无锁预读身份链 → 锁 SO 头
    `FOR UPDATE` → 锁出库单头 → 转移守卫 → **锁内单一库存闸**(Σ本单该 sku qty ≤ available,不足 `41902` 带逐 sku 明细)
    → 同事务建 receivable(偏唯一保幂等)。② **unreceive 穿仓守卫补全(还库存契约的债)**:撤销入库先锁受影响 SO 头
    (按 id 排序)→ 锁入库头 → 翻转后锁内派生校验受影响每 `(so,sku)` available ≥ 0,违反 `41710`(货已被出库,先撤销出库)。
  - **零金额出库单据(红线天然隔离)**:出库单/行/柜**无任何价格/成本/售价列**(纯仓单),读投影天然无红线;
    行不复制快照(经 join SO 行展示,SO 行冻结单一源头)。**应收 = 客户售价** → 整表 `receivable:read` 端点级门控
    (镜像 `payable:read`),不经出库 API 回显。应收金额确认事务内逐行 `quantize` 2dp(`ROUND_HALF_UP`)再求和。
  - **应收款账层(财务域全局表,独立迁移 `0026_receivable`)**:粒度 = 每张出库单一张;幂等键 = 活动行偏唯一;
    `balance` 生成列;`status`(未收/部分收/已收清)派生不落列(0 金额单余额 0 = 已收清);撤销出库同事务 void receivable。
    收款/核销 = 财务步(T15),本步只读列表。
  - **SKU 唯一 retrofit(上游,契约 §0-11)**:一 SKU 一价业务公理落 DB `UNIQUE(quotation_order_id, sku_id)` /
    `UNIQUE(sales_order_id, sku_id)`(迁移 `0024`)+ 报价 create/save service 前置守卫(重复 SKU `41412`);SO 行来自
    报价转单,继承唯一性。
  - **RBAC**:新增角色 **`LOGISTICS`(物流仓运)** = `outbound:*` + `shipment:*` + `sales:read`/`inventory:read`/`product:read`
    (组柜/封柜是仓运动作,不并入采购/销售;出库/发运/物流/报关四步同一操作者)。`SALES` 增只读 `outbound:read`/`shipment:read`/
    `receivable:read`(跟踪自家 SO 发货 + 应收=客户售价本就可见)。审计加 `ISSUE`/`UNISSUE` 动作 + `outbound_order`/`shipment_order` 资源类型。
  - **端点**:出库单 `POST /outbound-orders`、列表/详情、`PUT`(仅草稿整单重写+乐观锁)、`confirm`/`revert`/`cancel`;
    柜 `POST /shipments`、列表/详情(组柜工作台)、`PATCH`/`cancel`;`GET /sales-orders/{id}/outboundable-lines`(建单器
    数据源,守 `outbound:manage`);`GET /receivables`(🔴 `receivable:read`);SO 详情增 `related_outbound_orders` 块(条件下发)。
    单号 `NumberScope.OUTBOUND`(`OB{YYYYMM}####`)/ `SHIPMENT`(`SH{YYYYMM}####`);错误码段 19(出库 `419xx`)/ 20(柜 `420xx`)
    + `41710`(撤销入库穿仓)。迁移 `0024_quotation_so_sku_unique` + `0025_outbound` + `0026_receivable`。
  - **性能**:确认出库锁内派生(`available_by_sku` → `_balance_subquery`)`EXPLAIN ANALYZE` 全走 FK 索引(bitmap/index scan,
    无 seq scan),小规模 **≈0.5ms**;衰老方式同库存步 = 变慢有界,物化期权触发前不建。

- **发运(主流程第八步,分支 `feat/shipment-increment`)**:发运单 = 柜(承接出库骨架),本步把柜从「组柜容器」
  扩为承载**船务生命周期**(封柜/离港)。**发运不碰库存、不碰应收**——扣库存 + 建应收都在出库确认,发运只管柜的船务态。
  参照 SAP LE-TRA/D365/CargoWise 三段式,裁掉 TMS 多轴复杂度取**单线状态机**。
  - **状态机(model 层单一源头)**:柜 `OPEN→{LOADED,CANCELLED}` / `LOADED→{DEPARTED,OPEN}`(撤封柜纠错口)/
    `DEPARTED→{LOADED}`(撤离港纠错口,清 `atd`)/ `CANCELLED` 终态。**LOADED = 封柜事实点**:出库撤销守卫需要它
    (封柜后柜内出库单冻结,离港常在封柜数日后)。已装/已发柜取消 = 沿反向边走回(undepart→unload→撤出库→cancel),
    每步守卫自然把关。命名动作 = 特定边,守卫**锚定源态**(load 与 undepart 同目标 LOADED,只查目标会误放行)。
  - **船务字段(迁移 `0028`,加列 + 改 CHECK,零新表/零新 FK/零新索引)**:`booking_no`/`vessel_name`/`voyage_no`/
    `bl_no`/`port_of_loading`/`port_of_discharge`(String,全 nullable 逐步补录)+ `etd`/`eta`/`atd`(Date)+ `loaded_at`
    (DateTime,封柜确认置/撤封柜清)。`ck_shporders_status` 重建为 4 值。港口自由文本(唯一消费者=展示,消费者出现再升 UN/LOCODE)。
    日期不加 CHECK(`atd` 早于 `etd` = 提前离港,合法)。柜量月十位数级,100× 后仍小表,不预设索引。
  - **封柜守卫 + 编辑门禁**:封柜确认(`load`)要求柜内 **≥1 非 CANCELLED 出库单**(空柜 `42004`)且**全部 ISSUED**
    (存在草稿 `42003` 带草稿单号列表)。编辑门禁单一源头 = `SHIPMENT_EDITABLE_FIELDS_BY_STATUS`(status→可编辑字段集):
    OPEN 全开 / LOADED 锁柜物理组(船务组仍可改)/ DEPARTED 仅 `{bl_no,eta,note}` / CANCELLED 空。门禁 = **diff 式**
    (提交值≠库中值 且 字段∉可编辑集 → `42005` 带字段名;值未变即放行,对全量 payload 稳健)+ 乐观锁 `expected_updated_at`(冲突 `42006`)。
  - **出库撤销收紧(兑现出库契约预留)**:`revert_order`(ISSUED→DRAFT)锁序末尾追加**柜头 `FOR UPDATE`**
    (SO 头→出库单头→柜头,叶子锁),柜 `status≠OPEN` → 拒 `41910`(封柜后冻结,须先撤封柜);锁读防 TOCTOU。
    所有触柜写入口单向同序(发运侧只锁柜头),无环无死锁。
  - **RBAC**:**零新增权限点**,复用 `shipment:read`/`shipment:manage`(封柜/离港/撤销均 manage;LOGISTICS 出库/发运/物流/报关
    同一操作者)。审计加 `LOAD`/`UNLOAD`/`DEPART`/`UNDEPART` 四动词(`depart` extra 记 `atd`、`undepart` 记被清 atd)。
    新增字段全组非红线(船名/航次/港/提单/日期,零成本/售价/供应商)。
  - **端点**:柜 `POST /shipments`(可带船务字段)、列表(status 筛选扩 4 态 + 船务概览列)/详情(发运工作台)、
    `PATCH`(门禁+乐观锁)、`load`/`unload`/`depart`/`undepart`/`cancel`(全守 `shipment:manage`)。
    错误码段 20 补 `42003`/`42004`/`42005`/`42006`(`42002` 保持单义=非法转移)+ 出库段 `41910`。迁移 `0028_shipment_shipping_fields`。

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
# 至少改: DATABASE_URL 指向 fulfillment_dev、JWT_SECRET_KEY(任意 >=16 字符)、
#         SUPER_ADMIN_INITIAL_PASSWORD(必填,无默认值,漏配起不来)
# 本地开发建议: ENABLE_API_DOCS=true(打开 /docs;生产保持 false)

alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

启动时会自动跑幂等 seed:种入 `SUPER_ADMIN_EMAIL`/`SUPER_ADMIN_INITIAL_PASSWORD` 指定的管理员账号
(首次登录强制改密)、同步 RBAC 权限点。

对象存储默认 `STORAGE_BACKEND=local`(写入 `backend/private_uploads/attachments`),不需要额外起
MinIO。要在本地验证 S3/MinIO 路径,单独起一个 MinIO 容器并把 `STORAGE_BACKEND` 切成 `s3`
(见 `.env.example` 里注释的 `S3_*` 项)即可,不需要整套 `docker compose up`。商品图(`main_image`/
`images`/`sku.image`)与附件共用同一套 `Storage`(`local` 落同一目录,`s3` 即生产 S3 兼容云对象存储),没有
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

## 安全与会话

**会话机制**:登录返回 **15 分钟 access token**(前端 Zustand 纯内存,无 Web Storage 落点)+
**7 天滑动 refresh token**(httpOnly cookie,`SameSite=Lax`,路径限定 `/api/v1/auth`)。
access 过期后前端 401 时经 `POST /api/v1/auth/refresh` 单飞续期(并发请求共享一次刷新),
每次刷新**轮换** refresh cookie(滑动 7 天);`POST /api/v1/auth/logout` 清 cookie(幂等,
带有效 token 时写 LOGOUT 审计)。**吊销单一源头 = `users.token_version`**:改密/管理员重置
即 +1,旧 access/refresh 一并失效,不建 jti 黑名单。

**登录防爆破(两道)**:

1. **进程内限流**(第一道减速带):`(identifier, ip)` 维度,窗口 60s 内失败 ≥5 次锁 5 分钟
   (`LOGIN_RATE_LIMIT_*`)。**内存态**——重启即清、多进程/多实例不共享。
2. **账号级锁定**(第二道,落 `users` 行,换 IP/重启不绕过):连续失败达
   `ACCOUNT_LOCK_THRESHOLD`(默认 10)次 → 锁定 `ACCOUNT_LOCK_MINUTES`(默认 15)分钟,
   期间正确密码也拒(业务码 40010)、尝试不递增计数;到期自动解锁,登录成功或
   **管理员重置密码**(人工解锁通道)即清零解锁。迁移 `0023_account_lockout`。

**防枚举**:登录失败(用户不存在 / 密码错 / 已注销)统一返回同一个 401,真实原因只进审计;
账号锁定提示是例外(用户须知道为何登不上、找管理员),属可用性与防枚举的权衡。

**安全响应头**:后端与前端(`next.config.mjs`)统一下发 `X-Content-Type-Options: nosniff` /
`X-Frame-Options: DENY` / `Referrer-Policy: strict-origin-when-cross-origin`;HSTS 由
`ENABLE_HSTS` 控制(默认 false,接 HTTPS 后开启),只在后端/网关层下发。

**API 文档开关**:`ENABLE_API_DOCS`(默认 **false**,`/docs` `/redoc` `/openapi.json` 全部 404),
本地开发在 `backend/.env` 置 true;生产保持 false,不对公网暴露接口面。

**相关环境变量**(详见 `.env.example`):`SUPER_ADMIN_INITIAL_PASSWORD`(**必填,无默认值**)、
`ENABLE_API_DOCS`、`ENABLE_HSTS`、`ACCOUNT_LOCK_THRESHOLD` / `ACCOUNT_LOCK_MINUTES`、
`REFRESH_COOKIE_SECURE`。

> 早期 M0 的 `/api/v1/attachments` 最小上传端点(无类型/大小校验、无业务 RBAC、无任何消费方)
> 已下线;对象存储层与商品图直传(`/api/v1/uploads`,守 `product:manage`)不受影响。

### 公网部署安全约束

- **登录 IP 限流是进程内存态** → `uvicorn` **workers 必须 = 1**(多 worker/多实例各自计数,
  限流形同虚设;要横向扩展需先把限流迁到共享存储)。账号级锁定落库,不受此限。
- 公网暴露建议在**网关层**叠加全局限流(带宽/QPS/爆破防护),应用内限流只针对登录端点。
- **HTTPS 接入后**:`REFRESH_COOKIE_SECURE=true` + `ENABLE_HSTS=true` 一起打开
  (纯 HTTP 阶段两者都无效/被浏览器忽略,保持 false)。
- `ENABLE_API_DOCS` 生产保持 false;`SUPER_ADMIN_INITIAL_PASSWORD` 部署前改强口令。

## 容器部署(整机部署/演示)

```bash
cp .env.example .env   # 改 JWT_SECRET_KEY / POSTGRES_PASSWORD / SUPER_ADMIN_* 等敏感项
docker compose --env-file .env up -d --build db minio backend
```

起 `db`(独立于本地开发用的 brew PG)+ `minio`(演示对象存储)+ `backend`(容器内自动等库就绪→
`alembic upgrade head`→启动,见 `backend/docker-entrypoint.sh`)。`minio` 里业务用的 bucket
(`fulfillment-attachments`)由 `minio-init` 一次性服务自动建好(幂等,随 `backend` 一起触发,不需要
单独跑);生产走云对象存储时 bucket 由运维预先建好,没有对应的一次性服务。

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
