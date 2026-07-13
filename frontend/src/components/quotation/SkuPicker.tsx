"use client";
import { useCallback, useMemo, useRef, useState } from "react";
import { Select, Spin } from "antd";
import { catalogApi, type SkuSearchItem } from "@/lib/catalog";
import { display } from "@/lib/i18n";

/** 选中回传:报价行需要的最小信息(id + 展示名 + 单位 code)。 */
export interface PickedSku {
  sku_id: number;
  sku_code: string;
  name: string;
  unit: string;
}

/**
 * 可复用异步 SKU 选择器(报价行录入用)。防抖远程搜索 catalogApi.searchSkus,
 * 只取「可选货」(available=true → SKU/SPU 均 ACTIVE 未删)。红线:reference_price
 * 后端对无 product:manage 角色已脱敏,此处也不展示成本,只显示编号/名称/规格。
 */
export function SkuPicker({
  value,
  placeholder = "输入编号 / 名称 / 规格搜索",
  onPick,
  style,
}: {
  value?: number;
  placeholder?: string;
  onPick: (sku: PickedSku | null) => void;
  style?: React.CSSProperties;
}) {
  const [options, setOptions] = useState<SkuSearchItem[]>([]);
  const [fetching, setFetching] = useState(false);
  const seq = useRef(0);

  const doSearch = useCallback((q: string) => {
    const mine = ++seq.current;
    if (!q.trim()) {
      setOptions([]);
      return;
    }
    setFetching(true);
    catalogApi
      .searchSkus({ q, available: true, page: 1, size: 20 })
      .then((page) => {
        if (mine === seq.current) setOptions(page.items);
      })
      .catch(() => {
        if (mine === seq.current) setOptions([]);
      })
      .finally(() => {
        if (mine === seq.current) setFetching(false);
      });
  }, []);

  // 简单防抖(300ms),避免每键一请求。
  const debounced = useMemo(() => {
    let t: ReturnType<typeof setTimeout>;
    return (q: string) => {
      clearTimeout(t);
      t = setTimeout(() => doSearch(q), 300);
    };
  }, [doSearch]);

  return (
    <Select
      showSearch
      value={value}
      placeholder={placeholder}
      style={{ width: "100%", ...style }}
      filterOption={false}
      onSearch={debounced}
      notFoundContent={fetching ? <Spin size="small" /> : null}
      onChange={(v: number | undefined) => {
        const hit = options.find((o) => o.id === v);
        onPick(hit ? { sku_id: hit.id, sku_code: hit.sku_code, name: display(hit.name_i18n), unit: hit.unit } : null);
      }}
      options={options.map((o) => ({
        value: o.id,
        label: `${o.sku_code} · ${display(o.name_i18n)}`,
      }))}
    />
  );
}
