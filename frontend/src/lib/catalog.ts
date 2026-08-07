import { api } from "./api";
import { display } from "./i18n";
import { qs } from "./qs";

// ---- 类型(对齐后端 schemas/spu.py · sku.py · categories/units 路由)----

export interface CategoryNode {
  id: number;
  code: string;
  parent_code: string | null;
  level: number;
  is_leaf: boolean;
  is_active: boolean;
  name_i18n: Record<string, string>;
  sort_order: number;
  updated_at: string;
}

// SPU 三态生命周期(SKU 仍二态 ACTIVE/INACTIVE)。语义见 backend SpuStatus / lib/productStatus。
export type ProductStatus = "DRAFT" | "ACTIVE" | "INACTIVE";

// 规格归属层:spu=产品级(整个 SPU 一致)/ sku=变体轴(逐 SKU 取值)。见后端 category_spec_attributes.scope。
export type SpecScope = "spu" | "sku";

export type ImageType = "MAIN" | "GALLERY" | "DETAIL";

/** product_images 行(读)。 */
export interface ProductImage {
  id: number;
  image_key: string;
  image_type: ImageType;
  sort_order: number;
  sku_id: number | null;
}

/** SPU 图集写入项(封面 MAIN 恰 1 / 轮播 GALLERY / 详情 DETAIL)。 */
export interface ImageRefIn {
  image_key: string;
  image_type: ImageType;
  sort_order: number;
}

/** SKU 图集写入项(无 MAIN/DETAIL 语义,后端记 GALLERY)。 */
export interface SkuImageRefIn {
  image_key: string;
  sort_order: number;
}

export interface SpuOut {
  id: number;
  spu_code: string;
  category_code: string;
  name_i18n: Record<string, string>;
  brand: string | null;
  description: string | null;
  hs_code: string | null;
  /** 产品级规格(scope=spu),整个 SPU 一致。落库形状仅 key/value。 */
  spec_jsonb: SpecItem[];
  status: ProductStatus;
  created_by: number;
  created_at: string;
  updated_at: string;
}

/** 列表行:后端附加派生可用性 + 封面 key(main_image,无图为 null)。 */
export type SpuListItem = SpuOut & {
  has_active_sku: boolean; // 是否有在售 SKU(纯 SKU 状态,完备性告警口径,与详情一致)
  main_image: string | null;
  category_name_i18n: Record<string, string> | null;
};

/** 详情:图集全量 + 内嵌 SKU(每条带派生 available)+ 派生 has_available_sku。
 *  spec_display = 本 SPU 产品级规格的展示投影(后端单一解析)。 */
export type SpuDetail = SpuOut & {
  has_available_sku: boolean;
  category_name_i18n: Record<string, string> | null;
  /** 分类完整路径(根→叶),后端从 categories 树派生。用于详情页展示层级,末级=叶。 */
  category_path: { code: string; name_i18n: Record<string, string> }[];
  spec_display: SpecDisplayItem[];
  images: ProductImage[];
  skus: SkuDetailItem[];
};

/** 建/改 SPU 的返回:后端 _spu_with_images 回 SpuOut + 产品级 spec_display + 图集(不含 skus / 派生可用性)。 */
export type SpuWriteResult = SpuOut & { spec_display: SpecDisplayItem[]; images: ProductImage[] };

/** spec_jsonb 落库形状(§11 Part B:不含 unit,计量单位只住模板)。 */
export interface SpecItem {
  key: string;
  value: string | number | Record<string, string>;
}

/** 展示投影(后端 resolve_spec_display 单一解析):enum 值=选项 label_i18n,标量原样;带归属层 scope。 */
export interface SpecDisplayItem {
  key: string;
  label_i18n: Record<string, string> | null;
  value: string | number | Record<string, string> | null;
  unit: string;
  scope: SpecScope;
}

/** 展示串:`标签:值 单位`(值为 i18n 取展示语言),空则空串。消费后端 spec_display,不在前端各拼各的。 */
export function specDisplayText(items: SpecDisplayItem[] | undefined | null): string {
  return (items ?? [])
    .map((i) => {
      const label = display(i.label_i18n) || i.key;
      const val = typeof i.value === "object" && i.value !== null ? display(i.value) : i.value;
      return `${label}:${val ?? ""}${i.unit ? ` ${i.unit}` : ""}`;
    })
    .join(" / ");
}

/** 变体轴规格短串:只取 scope=sku 的轴属性,去标签、值+单位紧凑无空格、` / ` 连接。
 *  后端 compose_spec_text(单据行快照)的前端镜像 —— 规则须与其一致(值紧跟单位、` / ` 连接),
 *  唯一权威在后端,这里只做同款展示。enum 值在 spec_display 里已翻成 label_i18n(对象)→ display。 */
export function specAxisText(items: SpecDisplayItem[] | undefined | null, lang = "zh"): string {
  return (items ?? [])
    .filter((i) => i.scope === "sku")
    .map((i) => {
      const val = typeof i.value === "object" && i.value !== null ? display(i.value, lang) : i.value;
      return val === null || val === undefined || val === "" ? "" : `${val}${i.unit ?? ""}`;
    })
    .filter((s) => s !== "")
    .join(" / ");
}

export interface SkuOut {
  id: number;
  spu_id: number;
  sku_code: string;
  unit: string;
  /** 无 product:manage 时后端脱敏为 null。JSON 里 Decimal 可能是字符串。 */
  reference_price: string | number | null;
  weight_kg: string | number | null;
  length_cm: string | number | null;
  width_cm: string | number | null;
  height_cm: string | number | null;
  spec_jsonb: SpecItem[];
  name_i18n: Record<string, string>;
  search_text: string;
  status: ProductStatus;
  created_by: number;
  created_at: string;
  updated_at: string;
}

/** 详情/单取的 SKU:附自身图集 images + spec_display(SPU 产品级 ∪ SKU 轴,后端读时并集)。 */
export type SkuWithImages = SkuOut & { images: ProductImage[]; spec_display: SpecDisplayItem[] };
/** 详情内的 SKU:附图集 + 派生 available(SPU 停用则即便 SKU ACTIVE 也不可售)。 */
export type SkuDetailItem = SkuWithImages & { available: boolean };
/** 搜索行:后端不下发落库形状 spec_jsonb,改下发只 SKU 轴的展示投影 spec_display;
 *  附 spu_main_image(SPU 封面)供跨 SPU 图片回退。 */
export type SkuSearchItem = Omit<SkuOut, "spec_jsonb"> & {
  spu_main_image?: string | null;
  spec_display: SpecDisplayItem[];
};

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

export type SpecValueType = "string" | "number" | "enum";
export interface SpecOption {
  code: string;
  label_i18n: Record<string, string>;
}
export interface SpecSuggestion {
  key: string;
  label_i18n: Record<string, string>;
  value_type: SpecValueType;
  options: SpecOption[] | null;
  unit: string;
  sort_order: number;
  source: string;
  /** 归属层:spu 渲染到 SPU 表单、sku 渲染到 SKU 表单(前端按此分渲染)。 */
  scope: SpecScope;
}

export interface UnitOut {
  code: string;
  label_i18n: Record<string, string>;
  sort_order: number;
}

export interface CategorySaveBody {
  code?: string;
  parent_code?: string | null;
  name_i18n: Record<string, string>;
  sort_order: number;
}

/** SKU 写入的 spec 项(对齐后端 SkuSpecItemIn):新属性/新选项走 label_i18n 逃生口。 */
export interface SkuSpecItemIn {
  key?: string;
  value?: string | number | Record<string, string> | null;
  /** 仅"新增属性"分支落进模板行单位;已存在 key 后端忽略。 */
  unit?: string | null;
  label_i18n?: Record<string, string>;
}

export interface SkuWriteBody {
  spu_id: number;
  unit: string;
  reference_price?: string | number | null;
  weight_kg?: string | number | null;
  length_cm?: string | number | null;
  width_cm?: string | number | null;
  height_cm?: string | number | null;
  name_i18n: Record<string, string>;
  spec_items: SkuSpecItemIn[];
  images: SkuImageRefIn[];
}

export const catalogApi = {
  // ---- 参照(只读)----
  categoriesTree: (p?: { include_inactive?: boolean }) =>
    api.get<{ items: CategoryNode[] }>(
      `/api/v1/categories/tree${qs((p ?? {}) as Record<string, unknown>)}`,
    ),
  getCategory: (code: string) => api.get<CategoryNode>(`/api/v1/categories/${encodeURIComponent(code)}`),
  createCategory: (b: CategorySaveBody) => api.post<CategoryNode>("/api/v1/categories", b),
  updateCategory: (code: string, b: CategorySaveBody) =>
    api.put<CategoryNode>(`/api/v1/categories/${encodeURIComponent(code)}`, b),
  activateCategory: (code: string) =>
    api.post<CategoryNode>(`/api/v1/categories/${encodeURIComponent(code)}/activate`),
  deactivateCategory: (code: string) =>
    api.post<CategoryNode>(`/api/v1/categories/${encodeURIComponent(code)}/deactivate`),
  specSuggestions: (code: string) =>
    api.get<{ items: SpecSuggestion[] }>(`/api/v1/categories/${code}/spec-suggestions`),
  units: () => api.get<{ items: UnitOut[] }>("/api/v1/units"),

  // ---- SPU ----
  listSpus: (p: {
    category_code?: string;
    status?: string;
    keyword?: string;
    include_descendants?: boolean;
    page?: number;
    size?: number;
  }) => api.get<Page<SpuListItem>>(`/api/v1/spus${qs(p)}`),
  getSpu: (id: number) => api.get<SpuDetail>(`/api/v1/spus/${id}`),
  createSpu: (b: {
    category_code: string;
    name_i18n: Record<string, string>;
    brand?: string | null;
    description?: string | null;
    hs_code?: string | null;
    spec_items?: SkuSpecItemIn[];
    images: ImageRefIn[];
  }) => api.post<SpuWriteResult>("/api/v1/spus", b),
  updateSpu: (
    id: number,
    b: {
      name_i18n?: Record<string, string>;
      category_code?: string;
      brand?: string | null;
      description?: string | null;
      hs_code?: string | null;
      spec_items?: SkuSpecItemIn[];
      images?: ImageRefIn[];
    },
  ) => api.put<SpuWriteResult>(`/api/v1/spus/${id}`, b),
  setSpuStatus: (id: number, status: string) =>
    api.patch<SpuOut>(`/api/v1/spus/${id}/status`, { status }),
  deleteSpu: (id: number) => api.del<null>(`/api/v1/spus/${id}`),

  // ---- SKU ----
  searchSkus: (p: { q?: string; spu_id?: number; available?: boolean; page?: number; size?: number }) =>
    api.get<Page<SkuSearchItem>>(`/api/v1/skus${qs(p)}`),
  getSku: (id: number) => api.get<SkuWithImages>(`/api/v1/skus/${id}`),
  createSku: (b: SkuWriteBody) => api.post<SkuWithImages>("/api/v1/skus", b),
  updateSku: (id: number, b: Partial<SkuWriteBody>) => api.put<SkuWithImages>(`/api/v1/skus/${id}`, b),
  setSkuStatus: (id: number, status: string) =>
    api.patch<SkuOut>(`/api/v1/skus/${id}/status`, { status }),
  deleteSku: (id: number) => api.del<null>(`/api/v1/skus/${id}`),
};
