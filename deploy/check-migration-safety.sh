#!/usr/bin/env bash
# ============================================================
# 迁移安全检查
# 在 CI 拉起 deploy 前跑,检测新增 alembic migration 是否含破坏性操作
# 命中 → 退出 1,拦截自动部署,要求人工 review
#
# 跳过方式:commit message 含 [allow-destructive-migration]
# ============================================================
set -euo pipefail

BASE="${BASE_SHA:-HEAD~1}"
HEAD="${HEAD_SHA:-HEAD}"

echo "[check] 检查 ${BASE}..${HEAD} 区间新增的 migration"

# 新增 migration 文件(只检查新增,不检查既有)
NEW_MIGRATIONS=$(git diff --name-only --diff-filter=A "$BASE" "$HEAD" -- 'backend/alembic/versions/*.py' 2>/dev/null || true)

if [ -z "$NEW_MIGRATIONS" ]; then
    echo "[check] 无新增 migration"
    exit 0
fi

echo "[check] 新增 migration 文件:"
echo "$NEW_MIGRATIONS" | sed 's/^/  - /'
echo ""

# 破坏性操作 pattern
DANGEROUS='op\.drop_column|op\.drop_table|op\.drop_index|op\.drop_constraint|op\.execute.*DROP|op\.execute.*TRUNCATE|op\.execute.*DELETE|op\.alter_column.*type_='

UNSAFE=0
for f in $NEW_MIGRATIONS; do
    # 只检查 upgrade 函数内的操作,downgrade 里的 drop 是正常回滚
    UPGRADE_BLOCK=$(sed -n '/^def upgrade/,/^def downgrade/p' "$f" 2>/dev/null || true)
    if echo "$UPGRADE_BLOCK" | grep -E "$DANGEROUS" > /dev/null 2>&1; then
        echo "[check] ⚠️  $f 含破坏性操作:"
        echo "$UPGRADE_BLOCK" | grep -nE "$DANGEROUS" | sed 's/^/    /'
        echo ""
        UNSAFE=1
    fi
done

if [ "$UNSAFE" -eq 1 ]; then
    cat <<EOF
[check] ============================================================
[check] 自动部署已拦截:检测到破坏性迁移。
[check]
[check] 处理方式(任选其一):
[check]   1. 改成无损方案(expand-contract、可逆 add+rename 替代 drop)
[check]   2. 在 commit message 加 [allow-destructive-migration] 标记,确认数据可丢
[check]   3. 手动 SSH 到服务器跑 deploy.sh(完全跳过 CI 路径)
[check] ============================================================
EOF
    exit 1
fi

echo "[check] ✅ 所有新增 migration 安全"
