// 占位:容器启动时由 entrypoint.sh 覆盖为真实运行时环境(window.__ENV)。
// 本地开发直接跑 next dev 时不经 entrypoint,保持空对象,env.ts 回落 process.env.NEXT_PUBLIC_*。
window.__ENV = {};
