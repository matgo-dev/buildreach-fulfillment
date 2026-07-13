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
pnpm install   # 含 Ant Design(antd / @ant-design/nextjs-registry / @ant-design/icons)
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

- GitHub remote 已建:`origin` → `github.com/matgo-dev/buildreach-fulfillment`;仍待接:
  - 远端 CI(`.github/workflows/ci.yml` 尚未在真实 GitHub Actions 环境验证过)
  - 远端部署编排(目前本仓库无对应目录,后续按需补)
- `frontend/Dockerfile`:生产构建镜像待补(见上「容器部署」一节)。
- 前端界面:M1 未做(仅 M0 最小登录壳),随各模块后端稳定后逐步补(内部界面,中文)。
