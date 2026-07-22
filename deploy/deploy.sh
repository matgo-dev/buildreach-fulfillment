#!/usr/bin/env bash
# ============================================================
# 履约后台 统一部署脚本
#
# 适用于所有服务器(ECS 测试环境 / OVH 生产环境),由 GitHub Actions 或手动 SSH 调用。
# 反向代理由宿主 1Panel(OpenResty)管理,本脚本只负责容器编排。
#
# 流程:
#   备份 DB → 可选更新部署文件 → 登录镜像仓库 → 拉镜像 → 记录旧镜像 → 起容器 → 健康检查(失败自动回滚) → 清理
#
# 严禁改成含以下操作:
#   docker compose down -v / docker volume rm / docker system prune --volumes / rm -rf pgdata / git clean -fdx
# ============================================================
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/fulfillment}"
BACKUP_DIR="${BACKUP_DIR:-$APP_DIR/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-60}"
DEPLOY_REF="${DEPLOY_REF:-origin/main}"
BACKEND_HOST_PORT="${BACKEND_HOST_PORT:-8001}"
FRONTEND_HOST_PORT="${FRONTEND_HOST_PORT:-3001}"
IMAGE_TAG="${IMAGE_TAG:-}"
DEPLOY_SKIP_CODE_UPDATE="${DEPLOY_SKIP_CODE_UPDATE:-false}"
COMPOSE_FILE="docker-compose.production.yml"

cd "$APP_DIR"

echo "[deploy] =================================================="
echo "[deploy] 开始部署 $(date -Iseconds)"
echo "[deploy] APP_DIR=$APP_DIR  COMPOSE_FILE=$COMPOSE_FILE"
echo "[deploy] =================================================="

# ---- 0. 校验 .env.production ----
if [ ! -f .env.production ]; then
    echo "[deploy] .env.production 不存在,无法部署(首次部署见 deploy/README-deploy.md)"
    exit 1
fi
set -a
# shellcheck disable=SC1091
source .env.production
set +a

IMAGE_TAG="${IMAGE_TAG:-${RELEASE_TAG:-latest}}"
echo "[deploy] IMAGE_TAG=$IMAGE_TAG"

# 允许 CI/手动部署不改 .env.production 覆盖本次发布参数
if [ -n "${DEPLOY_CORS_ORIGINS:-}" ]; then
    export CORS_ORIGINS="$DEPLOY_CORS_ORIGINS"
fi
PUBLIC_ORIGIN="${DEPLOY_PUBLIC_ORIGIN:-${CORS_ORIGINS%%,*}}"
PUBLIC_ORIGIN="${PUBLIC_ORIGIN%/}"
if [ -z "$PUBLIC_ORIGIN" ]; then
    PUBLIC_ORIGIN="http://localhost"
    echo "[deploy] ⚠️  PUBLIC_ORIGIN 未设置,使用 $PUBLIC_ORIGIN"
fi
if [ -n "${DEPLOY_API_BASE_URL:-}" ]; then
    export API_BASE_URL="${DEPLOY_API_BASE_URL%/}"
elif [ -n "${DEPLOY_PUBLIC_ORIGIN:-}" ]; then
    export API_BASE_URL="$PUBLIC_ORIGIN"
fi
export BACKEND_HOST_PORT FRONTEND_HOST_PORT IMAGE_TAG API_BASE_URL

# ---- 1. 备份数据库(只在 DB 容器已运行时)。OVH 切托管 PG 后无 db 容器 → 跳过,依赖托管自动备份 ----
mkdir -p "$BACKUP_DIR"
if docker compose -f "$COMPOSE_FILE" ps db --status running 2>/dev/null | grep -q db; then
    BACKUP_FILE="$BACKUP_DIR/$(date +%Y%m%d-%H%M%S).sql.gz"
    echo "[deploy] [1/6] 备份数据库 → $BACKUP_FILE"
    docker compose -f "$COMPOSE_FILE" exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$BACKUP_FILE"
    BACKUP_SIZE=$(stat -c%s "$BACKUP_FILE" 2>/dev/null || echo "0")
    if [ ! -f "$BACKUP_FILE" ] || [ "$BACKUP_SIZE" -lt 1000 ]; then
        echo "[deploy] ❌ 备份异常(文件缺失或过小 ${BACKUP_SIZE} bytes)"
        rm -f "$BACKUP_FILE"
        exit 1
    fi
    find "$BACKUP_DIR" -name "*.sql.gz" -mtime "+$RETENTION_DAYS" -delete 2>/dev/null || true
    echo "[deploy]       ✅ 备份成功 ($(du -h "$BACKUP_FILE" | cut -f1))"
else
    echo "[deploy] [1/6] DB 容器未运行,跳过备份(首次部署 / 托管 PG)"
fi

PREV_SHA=$(git rev-parse HEAD 2>/dev/null || echo "-")

# ---- 2. 更新部署文件 ----
case "$DEPLOY_SKIP_CODE_UPDATE" in
    1|true|TRUE|yes|YES) SKIP_CODE_UPDATE=1 ;;
    *) SKIP_CODE_UPDATE=0 ;;
esac
if [ "$SKIP_CODE_UPDATE" -eq 1 ]; then
    echo "[deploy] [2/6] 跳过服务器 git 拉取(用 CI 已同步的部署文件)"
    NEW_SHA="$PREV_SHA"
else
    echo "[deploy] [2/6] 拉取最新代码 → $DEPLOY_REF"
    git fetch origin
    git reset --hard "$DEPLOY_REF"
    NEW_SHA=$(git rev-parse HEAD)
    [ "$PREV_SHA" = "$NEW_SHA" ] && echo "[deploy]       无更新($NEW_SHA)" || echo "[deploy]       $PREV_SHA → $NEW_SHA"
fi

# ---- 3. 拉镜像 ----
echo "[deploy] [3/6] 拉镜像(IMAGE_TAG=$IMAGE_TAG)"
if echo "${IMAGE_REGISTRY:-}" | grep -q "aliyuncs.com"; then
    if [ -n "${ACR_USERNAME:-}" ] && [ -n "${ACR_PASSWORD:-}" ]; then
        echo "[deploy]       登录阿里云 ACR..."
        echo "$ACR_PASSWORD" | docker login --username "$ACR_USERNAME" --password-stdin "${IMAGE_REGISTRY%%/*}"
    fi
elif [ -n "${GHCR_TOKEN:-}" ]; then
    echo "[deploy]       登录 GHCR..."
    echo "$GHCR_TOKEN" | docker login ghcr.io --username github-actions --password-stdin
fi
export IMAGE_REGISTRY="${IMAGE_REGISTRY:-ghcr.io/matgo-dev/buildreach-fulfillment}"
docker compose -f "$COMPOSE_FILE" --env-file .env.production pull backend frontend

# ---- 4. 记录旧镜像(回滚用)----
echo "[deploy] [4/6] 记录当前运行镜像"
OLD_BACKEND_IMAGE=$(docker inspect --format '{{.Config.Image}}' "$(docker compose -f "$COMPOSE_FILE" ps -q backend 2>/dev/null)" 2>/dev/null || true)
OLD_FRONTEND_IMAGE=$(docker inspect --format '{{.Config.Image}}' "$(docker compose -f "$COMPOSE_FILE" ps -q frontend 2>/dev/null)" 2>/dev/null || true)
echo "[deploy]       旧 backend  → ${OLD_BACKEND_IMAGE:-首次部署}"
echo "[deploy]       旧 frontend → ${OLD_FRONTEND_IMAGE:-首次部署}"

# ---- 5. 起容器 ----
echo "[deploy] [5/6] 启动容器"
docker compose -f "$COMPOSE_FILE" --env-file .env.production up -d --remove-orphans

# ---- 6. 健康检查(backend /healthz + frontend / 都过才算成功)----
check_health() {
    local url="$1" ok=0
    for i in $(seq 1 $((HEALTH_TIMEOUT_SECONDS / 2))); do
        if curl -fsS --max-time 5 "$url" > /dev/null 2>&1; then ok=1; break; fi
        sleep 2
    done
    echo "$ok"
}
echo "[deploy] [6/6] 健康检查(最多 ${HEALTH_TIMEOUT_SECONDS}s)..."
BACKEND_OK=$(check_health "http://localhost:${BACKEND_HOST_PORT}/healthz")
FRONTEND_OK=$(check_health "http://localhost:${FRONTEND_HOST_PORT}")
echo "[deploy]       backend=$BACKEND_OK frontend=$FRONTEND_OK"

if [ "$BACKEND_OK" -ne 1 ] || [ "$FRONTEND_OK" -ne 1 ]; then
    echo "[deploy] ⚠️  健康检查失败,最近日志:"
    docker compose -f "$COMPOSE_FILE" logs --tail=30 backend frontend 2>&1 | sed 's/^/         /'
    if [ -n "$OLD_BACKEND_IMAGE" ] && [ -n "$OLD_FRONTEND_IMAGE" ]; then
        echo "[deploy] 🔄 回滚到上一版本..."
        [ "$SKIP_CODE_UPDATE" -eq 0 ] && git reset --hard "$PREV_SHA" || true
        export IMAGE_TAG="${OLD_BACKEND_IMAGE##*:}"
        echo "[deploy]    回滚 IMAGE_TAG → $IMAGE_TAG"
        docker compose -f "$COMPOSE_FILE" --env-file .env.production up -d --remove-orphans
        ROLLBACK_OK=$(check_health "http://localhost:${BACKEND_HOST_PORT}/healthz")
        [ "$ROLLBACK_OK" -eq 1 ] && echo "[deploy] ✅ 回滚成功,已恢复到 $PREV_SHA" || echo "[deploy] ❌ 回滚后仍不健康,需人工介入"
    else
        echo "[deploy] ❌ 无旧镜像记录(首次部署),无法回滚,需人工介入"
    fi
    exit 1
fi

# ---- 清理(保留 volume)----
echo "[deploy] 清理 dangling 镜像 + 构建缓存"
docker image prune -f --filter "dangling=true" >/dev/null 2>&1 || true
docker builder prune -f --keep-storage=500MB >/dev/null 2>&1 || true

echo "[deploy] =================================================="
echo "[deploy] 部署成功 $(date -Iseconds)"
echo "[deploy]    image_tag → $IMAGE_TAG"
echo "[deploy]    backend   → http://localhost:${BACKEND_HOST_PORT}/healthz"
echo "[deploy]    frontend  → http://localhost:${FRONTEND_HOST_PORT}"
echo "[deploy]    public    → ${PUBLIC_ORIGIN}"
echo "[deploy] =================================================="
