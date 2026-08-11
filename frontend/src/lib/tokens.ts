/**
 * 代码层色板权威源头 —— 镜像 DESIGN.md §1 色表(人读权威表),数值须与 §1 一致。
 * tailwind.config.ts / AntdProvider / 组件一律从此处取值,不再各写裸 hex(单一源头,§单一源头硬约束)。
 * §1.3 状态徽标色在 status 里登记为精确 chip token,由 StatusTag 统一消费。
 */
export const colors = {
  // §1.1 主色 / 品牌(祖母绿:绿作点睛,不铺满)
  brand: "#15803D", //  主操作、链接(emerald-700)
  brandDark: "#116631", //  hover / active
  brandLight: "#16A34A", //  导航激活高亮块 / 链接 hover(emerald-600)
  brandAccent: "#FF6B35", //  强调点缀(封面星标等)
  sidebar: "#12302A", //  侧边栏背景(深墨绿,纯色不渐变 —— 渐变让底部像脏了一块)
  sidebarText: "#d6e4df", //  侧边栏未激活菜单文字(高对比,深底上细字才不糊)
  sidebarGroup: "#8aa39b", //  侧边栏分组标题(弱于菜单项但仍可读)
  sidebarLine: "rgba(255,255,255,0.10)", //  侧边栏内分隔发丝线
  // §1.2 中性 / 语义文字
  navy: "#102441", //  标题
  ink: "#1c314f", //  正文
  muted: "#6b7a90", //  辅助说明
  line: "#dbe4ea", //  分割线 / 卡片边框
  lineStrong: "#c9d8df", //  强调边框
  bg: "#f4f7f9", //  页面背景
  // §1.3 状态语义色
  success: "#0D9488", //  成功 / 在售 —— 走青,与品牌绿色相拉开(方案 A)
  info: "#1677ff", //  进行中 —— 显式钉死为蓝,不随 colorPrimary 变绿
  status: {
    success: {
      text: "#0f766e",
      bg: "#f0fdfa",
      border: "#99f6e4",
      dot: "#0D9488",
    },
    info: {
      text: "#2563eb",
      bg: "#eff6ff",
      border: "#bfdbfe",
      dot: "#1677ff",
    },
    neutral: {
      text: "#475569",
      bg: "#f1f5f9",
      border: "#cbd5e1",
      dot: "#94a3b8",
    },
    warning: {
      text: "#92400e",
      bg: "#fffbeb",
      border: "#fde68a",
      dot: "#f59e0b",
    },
    danger: {
      text: "#991b1b",
      bg: "#fef2f2",
      border: "#fecaca",
      dot: "#ef4444",
    },
  },
  // 基础原子(非 §1 语义色,组件通用)
  white: "#ffffff",
} as const;
