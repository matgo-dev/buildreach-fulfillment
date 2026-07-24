import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

// import.meta.dirname 要 Node ≥20.11,但 engines 允许 ≥20.10,低版本会得 undefined
// 令 outputFileTracingRoot 静默失效;用可移植写法,任意 Node 版本都拿得到本文件目录。
const projectRoot = dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 容器化生产构建:产出自包含 .next/standalone(server.js + 最小 node_modules),
  // 镜像 runner 阶段只拷这一份,不带 pnpm store symlink,体积小、启动快。
  output: "standalone",
  // 钉死 file-tracing 根为本项目目录:Next 15 会因机器上存在其它 lockfile
  // (如家目录 package-lock.json)把 workspace root 推断到别处,导致 standalone
  // 产物 tracing 错位。显式声明消除该不确定性。
  outputFileTracingRoot: projectRoot,
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
