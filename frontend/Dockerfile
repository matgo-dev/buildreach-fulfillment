# ============================================================
# 公司内部供应链履约系统 · 前端镜像(Next.js 14 · standalone)
# 多阶段:deps 装依赖 → builder 构建(构建时内联 API_BASE_URL)→ runner 只跑 standalone 产物
#
# API_BASE_URL 是浏览器访问后端的【公网地址】,在构建时内联进 bundle(见 next.config.mjs)。
# 每个环境各自 build,烤进自己的地址:初期=http://<ECS-IP>,生产=https://<域名>。
# compose 通过 build.args 从 .env 传入,所以同一份 compose、不同 .env 即可。
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
ARG API_BASE_URL
ENV API_BASE_URL=$API_BASE_URL \
    NEXT_TELEMETRY_DISABLED=1 \
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
# 静态资源(standalone 不含 .next/static,须单独拷)
COPY --from=builder --chown=nextjs:nextjs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
# 健康检查:node 20 自带全局 fetch;/ 未登录会客户端跳登录,SSR 仍返回 200
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://localhost:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.js"]
