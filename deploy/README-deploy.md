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
cp .env.example .env.production   # 按注释改:强口令、API_BASE_URL、CORS_ORIGINS、外部对象存储等
```

- ECS:`.env.production` 里 `API_BASE_URL` / `CORS_ORIGINS` = `http://<ECS_IP>`;`REFRESH_COOKIE_SECURE=false`。
- OVH:改 `https://<域名>`;`REFRESH_COOKIE_SECURE=true` + `ENABLE_HSTS=true`;对象存储必须指向外部 S3 兼容服务。
- 1Panel 建反向代理:`/api` → `127.0.0.1:17858`,其余 → `127.0.0.1:7858`;OVH 签证书(同前台流程)。

## 三、发布

- **ECS**:GitHub → Actions → **Build & Deploy** → Run workflow,选任意非 `release-v*` 分支。
- **OVH**:从 `release-v*` 分支/tag 触发。
- **手动**(服务器上):`IMAGE_TAG=<tag> bash deploy/deploy.sh`。
- **破坏性迁移**被 `check-migration-safety.sh` 拦截;确需 → commit message 加 `[allow-destructive-migration]`。
- **发布后核对版本**:`GET /api/v1/version` 返回当前部署的 commit / 分支 / 构建时间(CI build-args → 镜像 ENV 注入,同前台;本地 dev 显 `dev`)。

## 四、PG 数据持久化与备份取舍(当前)

当前 PG 采用**单机 Docker 容器 + named volume**:

- `docker-compose.production.yml` 的 `db` 服务使用 `postgres:16.4-alpine`。
- 数据目录挂到 Docker named volume `fulfillment_pgdata`(`pgdata:/var/lib/postgresql/data`)。
- 容器重建、镜像升级、应用重新部署不会删除数据库文件。

这解决的是**容器生命周期与数据库文件生命周期分离**;它不是灾备。服务器磁盘损坏、整机丢失、误删 volume、入侵删除本机文件时,volume 本身救不了数据。

当前已有一层**发布前本机备份**:`deploy.sh` 每次部署前,若 `db` 容器正在运行,会执行:

```bash
docker compose -f docker-compose.production.yml exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$BACKUP_FILE"
```

该备份的定位是:

- 发布失败或迁移异常时,提供发布前快照,方便短时间回滚/抢救。
- 误操作刚发生且服务器仍正常时,提供一个本机恢复点。
- **不等于异地灾备**:备份文件仍在同一台服务器的 `$APP_DIR/backups` 下,不能覆盖整机故障或本机文件被一起删除的风险。

短期取舍:

- 暂不接 OVH Managed PostgreSQL。
- 暂不做自动异地备份,因为目前还没有确定的异地存放资源。
- 暂不承诺灾难恢复能力;现阶段接受“单机持久化 + 发布前本机备份”的风险边界。
- 不新增复杂主备/复制方案,避免为了形式上的高可用引入更难维护的系统。

最低操作纪律:

- 禁止执行 `docker compose down -v`、`docker volume rm fulfillment_pgdata`、`docker system prune --volumes`。
- 高风险操作(迁移、批量导入、手工改库)前,先手动跑一次 `deploy.sh` 的同口径 `pg_dump` 或直接执行上面的备份命令。
- 若业务开始录入真实财务数据、外部人员开始正式使用、或出现不可接受的数据丢失风险,必须重新评估异地备份。

未来补齐顺序(有资源时再做):

1. 定时 `pg_dump`(每天一次,业务繁忙后每 6 小时一次)。
2. 同步到异地位置(OVH Object Storage / S3 兼容桶 / 另一台服务器)。
3. 备份校验(文件大小、gzip 可读、必要时临时库恢复抽检)。
4. 恢复演练文档与演练记录。
5. 如维护成本可接受,再评估托管 PG 或主备方案。

## 五、对象存储生产规则

生产环境必须使用**外部 S3 兼容对象存储**(如 OVH Object Storage),不得把业务附件/商品图片长期放在应用服务器本机 MinIO 中。

上线前 `.env.production` 必须满足:

- `DEPLOY_ENV=production`
- `STORAGE_BACKEND=s3`
- `S3_ENDPOINT_URL` 指向外部 HTTPS endpoint,不能是 `http://minio:9000`、`localhost`、`127.0.0.1`。
- `S3_ACCESS_KEY` / `S3_SECRET_KEY` / `S3_BUCKET` 填写真值,不能保留示例占位。
- `COMPOSE_PROFILES` 不得包含 `local-minio`。

`deploy.sh` 会在生产部署前执行上述校验,不满足则直接失败。

本机 MinIO 只允许用于 staging、临时演示或开发联调。若确需启用:

```bash
DEPLOY_ENV=staging
COMPOSE_PROFILES=local-minio
S3_ENDPOINT_URL=http://minio:9000
S3_ACCESS_KEY=minio
S3_SECRET_KEY=<staging-minio-password>
MINIO_ROOT_USER=minio
MINIO_ROOT_PASSWORD=<staging-minio-password>
```

此时 `minio` / `minio-init` 服务才会随 `local-minio` profile 启动,MinIO Console 仍只能绑定 `127.0.0.1` 并通过 SSH/服务器内网排查,禁止配置公网反向代理。

如果曾经用本机 MinIO 存过真实业务文件,切换到 OVH Object Storage 前需用 `mc mirror` 同步 bucket,再更新 `.env.production` 指向外部对象存储。
