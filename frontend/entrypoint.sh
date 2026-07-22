#!/bin/sh
# 容器启动时把运行时环境变量注入 public/__env.js,浏览器侧 <Script src="/__env.js"> 读取(window.__ENV)。
# 好处:镜像构建一次、API 地址等启动时给 —— 同一镜像可跑 ECS(staging,IP)与 OVH(prod,域名)。
# 用 node 生成 JSON,避免特殊字符转义。
set -e

ENV_FILE="/app/public/__env.js"

node -e "
  const env = {
    API_BASE_URL: process.env.API_BASE_URL || ''
  };
  const js = 'window.__ENV = ' + JSON.stringify(env) + ';';
  require('fs').writeFileSync('${ENV_FILE}', js);
  console.log('[entrypoint] __env.js ->', js);
"

exec node server.js
