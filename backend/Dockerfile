# ============================================================
# 公司内部供应链履约系统 · 后端镜像
# 多阶段构建:builder 装依赖,runtime 只拷 venv + 应用代码
# ============================================================

# ============= builder =============
FROM python:3.11.10-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

# Debian 12 (bookworm) 用 DEB822 格式的 sources 文件,sed 替换为阿里云镜像
# 国内不走阿里云,apt-get install build-essential 可能跑几十分钟
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 装 uv(从阿里云 PyPI 镜像装,不走 ghcr.io 拉镜像层)
RUN pip install --no-cache-dir uv==0.5.11

WORKDIR /app

# 先拷 lock 文件,利用 Docker layer 缓存(代码改不重装依赖)
COPY pyproject.toml uv.lock ./

# 装到固定 venv 路径,runtime 阶段直接拷
RUN uv venv /opt/venv \
    && VIRTUAL_ENV=/opt/venv uv pip install --no-cache -e .

# ============= runtime =============
FROM python:3.11.10-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    LANG=C.UTF-8 \
    PATH="/opt/venv/bin:$PATH"

# 运行时只需要 libpq 和 curl(healthcheck 用)
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        libpq5 \
        # python-magic 运行时(附件 MIME 检测)
        libmagic1 \
        # CJK 字体(中文不乱码)
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 appuser

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# 拷贝应用代码(走 .dockerignore 过滤)
COPY --chown=appuser:appuser . .

# entrypoint 需要可执行 + 创建上传目录（volume 挂载点）
RUN chmod +x docker-entrypoint.sh \
    && mkdir -p /app/uploads \
    && mkdir -p /app/private_uploads/attachments \
    && chown -R appuser:appuser /app/uploads /app/private_uploads

ARG BUILD_COMMIT=dev
ARG BUILD_BRANCH=-
ARG BUILD_COMMIT_AUTHOR=-
ARG BUILD_COMMIT_TIME=-
ARG BUILD_TIME=-
ENV BUILD_COMMIT=$BUILD_COMMIT
ENV BUILD_BRANCH=$BUILD_BRANCH
ENV BUILD_COMMIT_AUTHOR=$BUILD_COMMIT_AUTHOR
ENV BUILD_COMMIT_TIME=$BUILD_COMMIT_TIME
ENV BUILD_TIME=$BUILD_TIME

USER appuser

EXPOSE 8000

# 健康检查:30s 启动期内不算失败,后续每 10s 检一次,3 次失败标记 unhealthy
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
