"""构建版本端点 /api/v1/version —— 当前部署的代码版本(commit/分支/构建时间)。

对齐前台同名端点:元数据由 CI 经 Docker build-args → 镜像 ENV 注入(deploy.yml + Dockerfile
已就位),本地 dev 无注入时显 "dev"。公开只读、无业务数据、零红线 → 不挂权限守卫
(与 /healthz 同档,供部署核对与网关探活用)。
"""
from __future__ import annotations

import os

from fastapi import APIRouter

from app.core.exceptions import success

router = APIRouter(tags=["system"])


@router.get("/version", summary="当前部署版本")
async def get_version() -> dict:
    return success({
        "commit": os.getenv("BUILD_COMMIT", "dev"),
        "branch": os.getenv("BUILD_BRANCH", "-"),
        "author": os.getenv("BUILD_COMMIT_AUTHOR", "-"),
        "commit_time": os.getenv("BUILD_COMMIT_TIME", "-"),
        "build_time": os.getenv("BUILD_TIME", "-"),
    })
