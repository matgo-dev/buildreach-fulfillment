"use client";
import { useCallback, useEffect, useState } from "react";
import { App } from "antd";
import type { TablePaginationConfig } from "antd";
import type { Page } from "@/lib/catalog";
import { resolveBizError } from "@/lib/errorMessages";

/**
 * 列表页「请求-状态-分页」骨架:rows/total/page/loading/loadError + load。
 * 筛选参数由页面自持,拼进 fetcher(useCallback,依赖=筛选 state);
 * fetcher 变化即自动重查——与各页手写 load useCallback + useEffect 行为等价。
 * 页码复位仍由页面在筛选 handler 里 setPage(1)(与既有交互一致,排序变更不复位)。
 */
export function useListQuery<T>(
  fetcher: (q: { page: number; size: number }) => Promise<Page<T>>,
  {
    size = 20,
    errorMessage = "加载失败",
    auto = true,
  }: {
    /** 每页条数(列表页 20;选单抽屉 10)。 */
    size?: number;
    /** 加载失败 toast 兜底文案。 */
    errorMessage?: string;
    /** false 时不自动拉取(抽屉未打开等);翻转为 true 即拉取。 */
    auto?: boolean;
  } = {},
) {
  const { message } = App.useApp();
  const [rows, setRows] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const res = await fetcher({ page, size });
      setRows(res.items);
      setTotal(res.total);
    } catch (e) {
      setLoadError(true);
      message.error(resolveBizError(e, errorMessage));
    } finally {
      setLoading(false);
    }
  }, [fetcher, page, size, errorMessage, message]);

  useEffect(() => {
    if (auto) load();
  }, [auto, load]);

  /** Table pagination 统一配置(共 N 条 / 不换页距,与各页既有写法逐字一致)。 */
  const pagination: TablePaginationConfig = {
    current: page,
    total,
    pageSize: size,
    showSizeChanger: false,
    showTotal: (t) => `共 ${t} 条`,
    onChange: setPage,
  };

  return { rows, total, page, setPage, size, loading, loadError, load, pagination };
}
