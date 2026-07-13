import { api } from "./api";

// ---- 类型(对齐后端 schemas/spu.py · sku.py · categories/units 路由)----

export interface CategoryNode {
  code: string;
  parent_code: string | null;
  level: number;
  is_leaf: boolean;
  name_i18n: Record<string, string>;
  sort_order: number;
}

export type ProductStatus = "ACTIVE" | "INACTIVE";

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
  status: ProductStatus;
  created_by: number;
  created_at: string;
  updated_at: string;
}

/** 列表行:后端附加派生可用性 + 封面 key(main_image,无图为 null)。 */
export type SpuListItem = SpuOut & { has_available_sku: boolean; main_image: string | null };

/** 详情:图集全量 + 内嵌 SKU(每条带派生 available)+ 派生 has_available_sku。 */
export type SpuDetail = SpuOut & {
  has_available_sku: boolean;
  images: ProductImage[];
  skus: SkuDetailItem[];
};

/** 建/改 SPU 的返回:后端 _spu_with_images 只回 SpuOut + 图集(不含 skus / 派生可用性)。 */
export type SpuWriteResult = SpuOut & { images: ProductImage[] };

/** spec_jsonb 落库形状(§11 Part B:不含 unit,计量单位只住模板)。 */
export interface SpecItem {
  key: string;
  value: string | number | Record<string, string>;
}

export interface SkuOut {
  id: number;
  spu_id: number;
  sku_code: string;
  unit: string;
  /** 无 product:manage 时后端脱敏为 null。JSON 里 Decimal 可能是字符串。 */
  reference_price: string | number | null;
  spec_jsonb: SpecItem[];
  name_i18n: Record<string, string>;
  search_text: string;
  status: ProductStatus;
  created_by: number;
  created_at: string;
  updated_at: string;
}

/** 详情/单取的 SKU:附自身图集 images。 */
export type SkuWithImages = SkuOut & { images: ProductImage[] };
/** 详情内的 SKU:附图集 + 派生 available(SPU 停用则即便 SKU ACTIVE 也不可售)。 */
export type SkuDetailItem = SkuWithImages & { available: boolean };
/** 搜索行:附 spu_main_image(SPU 封面)供跨 SPU 图片回退。 */
export type SkuSearchItem = SkuOut & { spu_main_image?: string | null };

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
}

export interface UnitOut {
  code: string;
  label_i18n: Record<string, string>;
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
  name_i18n: Record<string, string>;
  spec_items: SkuSpecItemIn[];
  images: SkuImageRefIn[];
}

function qs(p: Record<string, unknown>): string {
  const q = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  });
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const catalogApi = {
  // ---- 参照(只读)----
  categoriesTree: () => api.get<{ items: CategoryNode[] }>("/api/v1/categories/tree"),
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
    images: ImageRefIn[];
  }) => api.post<SpuWriteResult>("/api/v1/spus", b),
  updateSpu: (
    id: number,
    b: {
      name_i18n?: Record<string, string>;
      category_code?: string;
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
