# buildreach-fulfillment

公司内部供应链履约系统 · 独立仓库(认证 / RBAC / 审计 / 存储底座 + 业务领域)。面向公司内部运营/采购/财务(**买方看不到**),与前台电商平台完全独立。

独立仓库、独立数据库、独立部署,不依赖 `buildreach` 主仓库。

## 进度

- **M0(已完成)**:工程基座——认证/JWT、RBAC(配置镜像 + 启动同步)、审计日志、Trace ID、附件存储薄接口、6 张基表 + 迁移。
- **M1(核心竖切,已完成)**:一条数据端到端——导入分类 → 种规格模板 → 建 SPU/SKU(i18n 形状 + JSONB 规格 + 中性编码)→ pg_trgm 搜索 → 录一张带规格快照的报价草稿。
  - 新模块:分类(只读导入)、分类规格建议模板、客户(最小档)、SPU/SKU、SKU 搜索、报价草稿。
  - 统一编号服务(`number_sequences` 表 + `allocate`):主数据全局号段 `SKU00000042`/`C000042`/`SPU00000042`,单据按年月号段 `Q2026070001`。
  - **不在 M1**:报价锁档/转销售/导出、采购/入库/库存/发货、各模块管理后台、翻译内容(内容纯中文,i18n 仅形状先行)。
- **商品目录做完整(已完成,分支 `feat/product-catalog`)**:M1 遗留的目录能力补齐。
  - **RBAC 细分**:新增权限点 `catalog:read`/`catalog:manage`(替代原粗粒度 `spu:manage`/`sku:manage`),
    新增角色 `CATALOG_OPERATOR`(商品运营,持 read+manage);`ADMIN` 只保留 `catalog:read` 作职责分离过渡桥,
    不再持 `catalog:manage`(商品增改上下架收口给 `CATALOG_OPERATOR`)。
  - **SPU 中性编码**:`spus.spu_code`(`SPU00000042`,复用统一编号服务)。
  - **逻辑删**:`spus`/`skus` 都加 `deleted_at`,物理行永不删,读路径默认过滤已删;`DELETE` 端点即置
    `deleted_at`。
  - **上下架 + 派生可用性**:`status`(`ACTIVE`/`INACTIVE`)是自身字段;“可用”是派生语义,不落表——
    `SKU 可用 ⟺ 自身 ACTIVE ∧ 未删 ∧ 所属 SPU ACTIVE ∧ 未删`(`app/services/sku_service.py::sku_available`)。
    `GET /api/v1/skus?available=1` 按此语义过滤,供消费侧(报价选货等)只看真正能卖的货。
  - **成本脱敏**:`skus.reference_price`(内部采购参考价)只有持 `catalog:manage` 的调用方能看到,否则序列化时
    置 `None`(`sku_out(..., include_cost=...)`)。
  - **商品图片**:`spus.main_image`(必填,创建校验 trim 后非空)/ `spus.images`(相册),`skus.image`
    (可选,回退 `spu.main_image`)。存储复用扩展后的 `Storage` 协议新增 `build_url`(展示 URL,OSS 可带
    `size` 走 `x-oss-process` 缩略)/ `create_upload`(前端直传描述);上传端点 `POST /api/v1/uploads`
    生成 `{key, upload_url, method}`,`STORAGE_BACKEND=local` 时另有 `PUT /api/v1/uploads/{key}` 本地接收
    ——key 形状强校验(`img/<uuid32>_<安全文件名>`)防路径穿越/越权覆盖,`content_type` 收窄到
    `jpeg/png/webp/gif`(显式排除 `image/svg+xml`,防存储型 XSS)。两个上传端点均守 `catalog:manage`。
  - 迁移:`0008_m1_catalog_completion`(`spu_code` + `deleted_at`)、`0009_catalog_images`(图片列)。

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
pnpm install
API_BASE_URL=http://localhost:8000 pnpm dev
```

访问 `http://localhost:3000`。

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
  - 远端部署编排(参考 `buildreach` 主仓库 `deploy/` 的模式,目前本仓库无对应目录)
- `frontend/Dockerfile`:生产构建镜像待补(见上「容器部署」一节)。
- 前端界面:M1 未做(仅 M0 最小登录壳),随各模块后端稳定后逐步补(内部界面,中文)。
