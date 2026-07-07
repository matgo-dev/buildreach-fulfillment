#!/usr/bin/env bash
# ============================================================
# 后端容器启动入口
# 1. 等数据库就绪
# 2. 跑 alembic upgrade head(迁移幂等,只跑未应用的)
# 3. exec uvicorn(应用 lifespan 内会自动跑 run_all_seeds,seed 已幂等)
#
# 注意:严禁在此处跑 alembic downgrade / drop / truncate / delete
# 注意:本仓库为纯底座(认证/RBAC/审计/存储),不含任何业务领域清洗脚本
# ============================================================

set -euo pipefail

echo "[entrypoint] === 启动 $(date -Iseconds) ==="

# ---- 等数据库就绪 ----
echo "[entrypoint] 等待数据库就绪..."
python - <<'PY'
import os
import time
import asyncio
import asyncpg
from urllib.parse import urlparse

url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg", "postgresql")
parsed = urlparse(url)


async def wait():
    for i in range(60):
        try:
            conn = await asyncpg.connect(
                host=parsed.hostname,
                port=parsed.port or 5432,
                user=parsed.username,
                password=parsed.password,
                database=parsed.path.lstrip("/"),
            )
            await conn.close()
            print(f"[entrypoint] 数据库就绪(第 {i + 1} 次尝试)", flush=True)
            return
        except Exception as e:
            print(f"[entrypoint] 等待 DB ({i + 1}/60): {e}", flush=True)
            await asyncio.sleep(2)
    raise SystemExit("[entrypoint] 数据库连接超时(2 分钟)")


asyncio.run(wait())
PY

# ---- 跑迁移 ----
echo "[entrypoint] alembic upgrade head"
alembic upgrade head

# ---- 启动应用(lifespan 自动触发 run_all_seeds,seed 已幂等)----
echo "[entrypoint] 启动应用:$*"
exec "$@"
