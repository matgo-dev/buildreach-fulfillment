# DESIGN.md — 履约平台设计系统

> 内部供应链履约平台（运营/采购/财务/管理，中文，桌面优先）的**唯一前端设计源头**。
> AI 工具 + 人类设计师都读这一份；`ff-ui-director` skill、`CLAUDE.md` 只指向它，不复制内容。
>
> **来源**：抽自前台仓库 `buildreach/DESIGN.md` 的「运营后台 (Admin) 轨」（主色本就是 `#003366`，与本平台一致）；**丢弃买方前台 (Mall/Teal) 轨**。视觉方向 = **B 现代 SaaS 克制型**。
> **与前台 admin 轨的有意偏离**：① 表格**不走斑马**（去掉 `even:bg`）；② 采用暗色侧栏 + 我们新增的交互/图片/权限约定。

---

## 1. 色彩

### 1.1 主色 / 品牌
```
brand        #003366   主操作、导航激活、链接
brand-dark   #002244   hover / active
brand-mid    #0F4C81   次要蓝
brand-accent #FF6B35   强调（少量点缀，如未读/重点标记；不与主操作抢戏）
sidebar      #0A1929   侧边栏背景（暗色）
```

### 1.2 中性 / 语义文字
```
navy   #102441   标题
ink    #1c314f   正文
muted  #6b7a90   辅助说明
line   #dbe4ea   分割线 / 卡片边框
line-strong #c9d8df  强调边框
bg     #f4f7f9   页面背景
```

### 1.3 状态色 — 业务状态映射到语义色（不单靠颜色，配点+文字）
| 业务状态 | 语义 | 文字 | 底 | 圆点 |
|---|---|---|---|---|
| 在售 | success | emerald-800 `#065f46` | emerald-50 `#ecfdf5` | emerald-500 `#10b981` |
| 停用 | neutral | slate-600 `#475569` | slate-100 `#f1f5f9` | slate-400 `#94a3b8` |
| 草稿 | warning | amber-800 `#92400e` | amber-50 `#fffbeb` | amber-500 `#f59e0b` |
| （危险操作）| danger | red-800 `#991b1b` | red-50 `#fef2f2` | red-500 `#ef4444` |

---

## 2. 排版

字体栈：
```css
font-family: ui-sans-serif, system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
```
数字列用 `font-variant-numeric: tabular-nums`。

| 用途 | 类 | 字重 |
|---|---|---|
| 页面大标题 | `text-xl` | `font-black` |
| 区块标题 | `text-base`/`text-lg` | `font-semibold`/`font-bold` |
| 英文小标签 | `text-[11px] uppercase tracking-widest` | `font-extrabold` |
| 表格/正文 | `text-sm` | `font-normal` |
| 辅助说明 | `text-xs` | `font-normal` |
| 徽章/标签 | `text-[11px]`/`text-[10px]` | `font-medium`/`font-bold` |

文字色：标题 `navy` / 正文 `ink`(或 slate-700) / 辅助 `muted` / 链接 `brand` / 禁用 gray-300。

---

## 3. 间距（4px 网格，不出现随意值如 `p-[13px]`）
`1`=4 `2`=8 `3`=12 `4`=16(卡片默认) `5`=20 `6`=24(页面/区块) `8`=32。
区块间 `space-y-4/5`；网格列 `gap-3/4`。

---

## 4. 圆角与阴影
| 场景 | 值 |
|---|---|
| 卡片 | `rounded-lg` (8px) |
| 按钮 / 输入 | `rounded-md` (6px) |
| 徽章/标签 | `rounded-full` |
| 弹窗 / 抽屉 | `rounded-xl` |

阴影：`shadow-card`（卡片默认，轻）；弹层更重。**B 用轻阴影/细线分隔，不用重描边、不用斑马。**

---

## 5. 组件

> **组件库 = Ant Design 5+（`ConfigProvider` 主题令牌对齐本文 token：`colorPrimary=#003366`、`borderRadius=6`、`fontSize=14`、Table 无斑马）。** 下列各组件的类名/规格是**视觉规格**（间距、圆角、状态色、交互载体），实现落在 AntD 组件上、由主题令牌保证一致；纯展示的轻组件（StatusChip/缩略图等）可用 Tailwind 直接写。二者只此一套令牌源头，勿在别处另立色板。

- **Button**（纯色无渐变，AntD `type` 映射：主操作 `primary` / 次要 `default` / 工具栏 `text` / 危险 `danger`）：`default`(brand 主操作) / `outline`(次要) / `ghost`(工具栏) / `destructive`(危险)。
- **Card**：`rounded-lg border border-gray-200 bg-white`。扁平、不套娃。
- **Input**：`h-10 rounded-md border-slate-300 bg-white px-3 text-sm`，focus `ring-2 ring-brand`。
- **Table**：表头 `bg-slate-50 text-xs text-gray-500 font-medium`；行 `border-t border-gray-100 hover:bg-blue-50/30`；**行高 ~36px**；操作列 `whitespace-nowrap`。**不用斑马**（`even:bg` 去掉——与前台 admin 的有意偏离）。
- **Badge/StatusChip**：`rounded-full px-2 py-0.5 text-[11px] font-medium` + 圆点，按 §1.3 状态色。
- **Drawer（详情/表单主载体）**：右侧滑出，遮罩 `bg-black/30`，容器白底 `rounded-xl` 左描边 + 轻阴影；含「打开完整详情页」出口。
- **Toast**：`fixed top-4 居中 z-[9999]`，`rounded-lg px-5 py-3 shadow-lg`。
- **Modal**：遮罩 `inset-0 z-50 bg-black/40`，容器 `max-w-md rounded-xl p-6`（仅用于确认类；表单优先抽屉）。

---

## 6. 布局骨架（满屏铺满 admin shell）
```
┌─ Header（顶栏：用户/登出/面包屑） ─────────────┐
├──┬────────────────────────────────────────────┤
│ S│                                            │
│ i│  main  (flex-1 overflow-y-auto p-6)         │
│ d│  ← 吃满剩余宽高；内容满宽                     │
│ e│                                            │
├──┴────────────────────────────────────────────┤
```
- Sidebar：`w-60`，背景 `#0A1929`（暗色），可折叠。
- **满屏**：主内容吃满宽高，不居中窄栏。**但**表单/详情正文有内部最大宽度（字段别拉超宽，按 1–2 列分组）；超宽屏(27″+)给内容上限或右侧留白。

---

## 7. 交互约定（平台级，任何列表/详情/表单默认行为）
- **列表排序**：时间列（及金额等数值列）默认可排序，表头 ↕/↓。
- **列表工具条统一次序**（所有列表页一致，报价管理为范式）：**[单据状态 Segmented（全部+各态，≤5 平铺）] → [搜索框] → [参照维度下拉（供应商等，可选）] → [页面特有开关]**。状态永远最左、搜索紧随其后。
- **次要枚举列不占工具条**：币种/采购进度等**次要枚举维度走列头下拉筛选**（AntD column `filters`，触发服务端过滤），工具条只留主轴（状态）+搜索+参照维度。基数 >5 的参照维度（品类/供应商）→ 下拉。
- **行下钻**：点行 → 右侧抽屉快查/轻编辑；重场景（多 tab/子表）走「打开完整详情页」。行主操作=看详情，编辑/停用放行尾图标。
- **层级树筛选**：树可展开到叶子；选**任意层级** → 按整棵子树过滤（code 前缀匹配）+ 面包屑 + 「含子类/仅本级」开关（默认含子类）。业务**归属**通常限叶子。
- **单据链接降级**：上/下级单号(来源报价 / 来源销售单 / 关联采购单等)**出现即链接**,单号即入口(SAP 单据流 / NetSuite Related Records 共性)。但**当前角色无目标页权限时降级为纯文本**——号可见(单号非红线)、不可点,绝不渲染点了撞 403 的死链(反例=Odoo)。落点:`Can perm={目标页权限} fallback={<span>{号}</span>}`。红线是点进去的**内容**(由目标页守卫 + 后端脱敏),不是号本身。
- **危险操作**：确认时讲**业务后果**，不只"确定吗"。

---

## 8. 图片（两级 + 回退 + 阿里云 OSS）
- **模型**（规范化独立表 `product_images`，存 object key，非 URL）：SPU 图与 SKU 图同表，靠 `sku_id` 区分层级（`sku_id IS NULL` = SPU 级）。每行 `image_type ∈ {MAIN, GALLERY, DETAIL}`（DB CHECK 兜底）。**封面 = 该 SPU 唯一一行 `MAIN`（`sku_id IS NULL`）**，≤1 由部分唯一索引硬保证。**身份键 = `image_key`**，写接口按 key 声明期望图集、后端 reconcile 按 key 对账到期望态。
- **张数上限**（后端 schema 校验）：SPU 级 主图组（`MAIN`+`GALLERY`）≤6（且恰 1 张 `MAIN`）/ 详情（`DETAIL`）≤12；SKU 级图 ≤6，一律记 `GALLERY`（无 `MAIN`/`DETAIL` 语义）。
- **回退**：SKU 无自有图时用 **SPU 封面**（封面取 `MAIN`，无则 `GALLERY` 最小 `sort_order`）。
- **尺寸靠存储层实时处理**（OSS `?x-oss-process=image/resize,w_80`列表 / `w_400`详情），不自生成缩略图、不存多份。
- **列表缩略图默认关**（密度优先），主图放详情/抽屉。
- **存储抽象**：统一 `Storage` 协议（`build_url`/`public_url`/`create_upload`/`save`/`open`/`delete`/`exists`），工厂 `get_attachment_storage()` 按 `STORAGE_BACKEND` 选实现——`local`→`LocalDiskStorage`（默认）/ `s3`→`S3Storage`（本地 MinIO・生产阿里云 OSS，S3 兼容端点），业务零改动。**本地预览走 `GET /media/{key}`（仅 `STORAGE_BACKEND=local` 启用；生产 `<img>` 直连公读桶、不经本端点）**。

---

## 9. 权限红线（一等约束）
成本 / 采购价 / 供应商 / 应付 / 付款 / 内部备注等**红线字段，对无权角色绝不可见**——**列表、详情、接口响应都不下发真值**（后端脱敏为 null，非仅前端隐藏）。渲染层按角色控制，交叉核对 `frontend/src/config/permission-matrix.ts`。

---

## 10. z-index
Toast `9999` / Modal 遮罩 `50` / 抽屉 `40` / 用户菜单 `200` / 顶栏 `80`。不随意写 `z-[999]`。

---

## 11. 规则
1. **不发明新色值/字号** — 只用上表 token。**颜色只在 `tailwind.config.ts` 定义一次（语义命名 brand/sidebar/status-*，可选 CSS 变量兜底），组件只用 token 名（`bg-brand`），永不写裸 hex（`#003366`）。改色号 = 改 config 一处，全站更新。**
2. **间距用 4px 网格**。
3. **后台按钮用 AntD 简洁风，不加渐变**（前台 Mall 的 pill/渐变风严禁用于本平台）。
4. **hover 必须有反馈**（颜色/阴影至少一种）。
5. **操作列 `whitespace-nowrap`**。
6. **红线字段后端脱敏**，不靠前端藏。
7. **表单优先抽屉，确认类才用 Modal**。
8. 表格**不用斑马**（本平台 B 风格）。

---

## 12. 数据模型与展示原则

- **模板正规化、SKU 值文档化**：可配置模板/字典（如分类规格属性）用正规化行；实例值（SKU `spec_jsonb`）存 JSONB 文档，别过度正规化。
- **身份用稳定 key、展示用 `label_i18n`**：属性/枚举**对外引用用稳定字符串 key**——种子=有意义英文（`material`/`carbon_steel`），运营新增=自动生成（`a_<id>`/`v_<id>`），**不用自增 id 引用**（跨环境不稳）；表内部仍有 id PK。运营录中文即可（进 `label_i18n.zh`）、英文选填、**不自动翻译**。
- **枚举存 code、展示翻译**：`spec_jsonb` 存 code，展示用 `options[].label_i18n` 翻成当前语言；`options` 形状 `[{"code":"...","label_i18n":{...}}]`。利于英文/斯瓦希里报价。
