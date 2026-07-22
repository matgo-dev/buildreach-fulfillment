/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 容器化生产构建:产出自包含 .next/standalone(server.js + 最小 node_modules),
  // 镜像 runner 阶段只拷这一份,不带 pnpm store symlink,体积小、启动快。
  output: "standalone",
  // API_BASE_URL 非 NEXT_PUBLIC_ 前缀,需在此显式声明才能被内联进浏览器 bundle。
  env: {
    API_BASE_URL: process.env.API_BASE_URL,
  },
  // 基础安全响应头(与后端同一组;HSTS 留给后端/网关层按 HTTPS 接入情况下发,不在此配)。
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
