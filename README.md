# buildreach-fulfillment

公司内部供应链履约系统 · 独立后端仓库(认证 / RBAC / 审计 / 存储底座;M0 阶段不含任何业务领域代码)。

独立仓库、独立数据库、独立部署,不依赖 `buildreach` 主仓库。

## 本地起法(占位,后续任务补全)

```bash
cd backend
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
# alembic upgrade head / uvicorn app.main:app --reload 等命令待 app/ 填充后补充
```
