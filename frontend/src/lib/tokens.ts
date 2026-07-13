/**
 * 代码层色板权威源头 —— 镜像 DESIGN.md §1 色表(人读权威表),数值须与 §1 一致。
 * tailwind.config.ts / AntdProvider / 组件一律从此处取值,不再各写裸 hex(单一源头,§单一源头硬约束)。
 * §1.3 状态色不在此:经 AntD 语义色(success/warning/error)应用,代码无裸 hex 消费者,出现时再收进来。
 */
export const colors = {
  // §1.1 主色 / 品牌
  brand: "#003366", //  主操作、导航激活、链接
  brandDark: "#002244", //  hover / active
  brandMid: "#0F4C81", //  次要蓝 / 链接 hover
  brandAccent: "#FF6B35", //  强调点缀(封面星标等)
  sidebar: "#0A1929", //  侧边栏背景(暗色)
  // §1.2 中性 / 语义文字
  navy: "#102441", //  标题
  ink: "#1c314f", //  正文
  muted: "#6b7a90", //  辅助说明
  line: "#dbe4ea", //  分割线 / 卡片边框
  lineStrong: "#c9d8df", //  强调边框
  bg: "#f4f7f9", //  页面背景
  // 基础原子(非 §1 语义色,组件通用)
  white: "#ffffff",
} as const;
