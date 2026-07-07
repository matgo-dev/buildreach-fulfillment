/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // API_BASE_URL 非 NEXT_PUBLIC_ 前缀,需在此显式声明才能被内联进浏览器 bundle。
  env: {
    API_BASE_URL: process.env.API_BASE_URL,
  },
};

export default nextConfig;
