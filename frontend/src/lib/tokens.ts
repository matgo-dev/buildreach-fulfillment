/**
 * 代码层色板权威源头 —— 镜像 DESIGN.md §1 色表(人读权威表),数值须与 §1 一致。
 * tailwind.config.ts / AntdProvider / 组件一律从此处取值,不再各写裸 hex(单一源头,§单一源头硬约束)。
 * §1.3 状态色经 AntD 语义令牌(colorSuccess/colorInfo/…)统一下发,故 success/info 在此登记为
 * AntD 的输入值,其余(warning/error/default)沿用 AntD 预设、无裸 hex 消费者。
 */
export const colors = {
  // §1.1 主色 / 品牌(祖母绿:绿作点睛,不铺满)
  brand: "#15803D", //  主操作、链接(emerald-700)
  brandDark: "#116631", //  hover / active
  brandLight: "#16A34A", //  导航激活高亮块 / 链接 hover(emerald-600)
  brandAccent: "#FF6B35", //  强调点缀(封面星标等)
  sidebar: "#0B1E1A", //  侧边栏背景(深墨绿)
  sidebarDeep: "#0E241F", //  侧边栏渐深(自上而下渐变落点)
  sidebarText: "#9fb3ac", //  侧边栏未激活菜单文字
  sidebarGroup: "#5c726c", //  侧边栏分组标题
  // §1.2 中性 / 语义文字
  navy: "#102441", //  标题
  ink: "#1c314f", //  正文
  muted: "#6b7a90", //  辅助说明
  line: "#dbe4ea", //  分割线 / 卡片边框
  lineStrong: "#c9d8df", //  强调边框
  bg: "#f4f7f9", //  页面背景
  // §1.3 状态语义色(交给 AntD 派生底/边)
  success: "#0D9488", //  成功 / 在售 —— 走青,与品牌绿色相拉开(方案 A)
  info: "#1677ff", //  进行中 —— 显式钉死为蓝,不随 colorPrimary 变绿
  // 基础原子(非 §1 语义色,组件通用)
  white: "#ffffff",
} as const;
