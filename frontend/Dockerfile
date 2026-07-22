# ============================================================
# 公司内部供应链履约系统 · 前端镜像(Next.js 14 · standalone)
# 多阶段:deps 装依赖 → builder 构建 → runner 只跑 standalone 产物
#
# API_BASE_URL 不在构建时写死,由容器启动的 entrypoint.sh 生成 public/__env.js 运行时注入
# (见 src/lib/env.ts 的 window.__ENV)。同一镜像可跑 ECS(IP)与 OVH(域名)。
# ============================================================

# ============= deps =============
FROM node:20.18-slim AS deps
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# ============= builder =============
FROM node:20.18-slim AS builder
RUN corepack enable
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production
RUN pnpm build

# ============= runner =============
FROM node:20.18-slim AS runner
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
WORKDIR /app
RUN useradd -m -u 1000 nextjs
# standalone 自包含产物:server.js + 运行所需最小 node_modules
COPY --from=builder --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/.next/static ./.next/static
# public(含 __env.js 占位,运行时被 entrypoint 覆盖)+ 运行时注入脚本
COPY --from=builder --chown=nextjs:nextjs /app/public ./public
COPY --from=builder --chown=nextjs:nextjs /app/entrypoint.sh ./entrypoint.sh
USER nextjs
EXPOSE 3000
# 健康检查:node 20 自带全局 fetch;/ 未登录会客户端跳登录,SSR 仍返回 200
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://localhost:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
# entrypoint 先写 __env.js,再 exec node server.js
CMD ["sh", "entrypoint.sh"]
