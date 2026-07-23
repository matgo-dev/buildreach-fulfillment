# 履约后台 · 部署手册

CI 构建镜像 → 推 ACR(阿里云,给 ECS)/ GHCR(给 OVH)→ SSH 到服务器跑 `deploy.sh`(拉镜像 → 起容器 → 健康检查 → 失败自动回滚)。反向代理 + TLS 由宿主 **1Panel(OpenResty)** 承载,不在 compose 内。

- **ECS = Staging**:非 `release-v*` 分支手动触发 → 从 ACR 拉,走 IP + http。
- **OVH = Production**:`release-v*` 分支手动触发 → 从 GHCR 拉,走域名 + https。

## 一、GitHub 配置(一次性)

**Variables**(Settings → Secrets and variables → Actions → Variables):

| 变量 | 值 |
|---|---|
| `ACR_REGISTRY` | `crpi-xxxx.cn-hangzhou.personal.cr.aliyuncs.com` |
| `ACR_IMAGE_REGISTRY` | `crpi-xxxx.cn-hangzhou.personal.cr.aliyuncs.com/<命名空间>` |

**Secrets**:

| 密钥 | 用途 |
|---|---|
| `ACR_USERNAME` / `ACR_PASSWORD` | 推 ACR + ECS 拉 ACR |
| `ECS_HOST` / `ECS_USER` / `ECS_SSH_KEY` | 部署到 ECS |
| `OVH_HOST` / `OVH_USER` / `OVH_SSH_KEY` / `OVH_PUBLIC_ORIGIN` | 部署到 OVH(如 `https://erp.matgohq.com`) |
| `GHCR_TOKEN` | OVH 拉 GHCR(`read:packages`) |

**Environments**:建 `staging`、`production` 两个(可加保护规则,如 production 需人工审批)。

## 二、服务器首次准备(ECS / OVH 各一次)

```bash
sudo mkdir -p /opt/fulfillment && cd /opt/fulfillment
# 放入 docker-compose.production.yml + deploy/(CI 首次会自动 rsync,手动首部署则先 git clone 或 scp)
cp .env.example .env.production   # 按注释改:强口令、API_BASE_URL、CORS_ORIGINS 等
```

- ECS:`.env.production` 里 `API_BASE_URL` / `CORS_ORIGINS` = `http://<ECS_IP>`;`REFRESH_COOKIE_SECURE=false`。
- OVH:改 `https://<域名>`;`REFRESH_COOKIE_SECURE=true` + `ENABLE_HSTS=true`。
- 1Panel 建反向代理:`/api` → `127.0.0.1:17858`,其余 → `127.0.0.1:7858`;OVH 签证书(同前台流程)。

## 三、发布

- **ECS**:GitHub → Actions → **Build & Deploy** → Run workflow,选任意非 `release-v*` 分支。
- **OVH**:从 `release-v*` 分支/tag 触发。
- **手动**(服务器上):`IMAGE_TAG=<tag> bash deploy/deploy.sh`。
- **破坏性迁移**被 `check-migration-safety.sh` 拦截;确需 → commit message 加 `[allow-destructive-migration]`。
- **发布后核对版本**:`GET /api/v1/version` 返回当前部署的 commit / 分支 / 构建时间(CI build-args → 镜像 ENV 注入,同前台;本地 dev 显 `dev`)。

## 四、上线前切托管(OVH 生产,登记待办)

当前库/对象存储是**容器**(与前台一致,`deploy.sh` 每次部署前 `pg_dump` 备份)。OVH 上线、灌真实财务数据前切托管:

1. **PG → OVH Managed PostgreSQL**:`docker-compose.production.yml` 去掉 `db` 服务,`.env.production` 的 `DATABASE_URL` 直接指托管实例(compose 里 backend 的 `DATABASE_URL` 改为读 `${DATABASE_URL}` 透传)。备份交 OVH 托管。
2. **对象存储 → OVH Object Storage**:去掉 `minio` / `minio-init`,`S3_ENDPOINT_URL` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` 指 OVH;bucket 面板预建。
3. 数据迁移:`pg_dump | psql` 灌托管 PG;`mc mirror` 把 minio bucket → OVH Object Storage。
