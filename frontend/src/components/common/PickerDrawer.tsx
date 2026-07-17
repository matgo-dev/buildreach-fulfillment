"use client";
import type { ReactNode } from "react";
import { Button, Drawer, Space, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { Page } from "@/lib/catalog";
import { useListQuery } from "@/hooks/useListQuery";
import { ListErrorState } from "@/components/common/ListErrorState";

/**
 * 「Drawer + 筛选 + 分页 Table + 行尾选择」选单骨架(采购选 SO / 入库选 PO 共用)。
 * 筛选 state 由调用方自持(变化令 fetcher 重建即自动重查);toolbar 以 render prop
 * 拿到 resetPage,在筛选 handler 里与自身 setState 同批调用(镜像各页 setPage(1) 惯例)。
 * 即时搜索无分页的 ProductPickerDrawer 交互模型不同,不走此骨架。
 */
export function PickerDrawer<T extends object>({
  title,
  open,
  onClose,
  onPick,
  columns,
  fetcher,
  toolbar,
  errorMessage,
  emptyText,
  scrollX,
  rowKey = "id",
}: {
  title: string;
  open: boolean;
  onClose: () => void;
  /** 选中一行(行尾「选择」按钮)。 */
  onPick: (row: T) => void;
  /** 业务列;行尾「选择」列由本组件统一追加。 */
  columns: ColumnsType<T>;
  fetcher: (q: { page: number; size: number }) => Promise<Page<T>>;
  toolbar: (ctx: { resetPage: () => void }) => ReactNode;
  errorMessage: string;
  emptyText: string;
  scrollX: number;
  rowKey?: string;
}) {
  const { rows, setPage, loading, loadError, load, pagination } = useListQuery<T>(fetcher, {
    size: 10,
    errorMessage,
    auto: open,
  });

  const allColumns: ColumnsType<T> = [
    ...columns,
    {
      title: "",
      key: "action",
      width: 72,
      fixed: "right",
      render: (_: unknown, r) => (
        <Button type="link" size="small" onClick={() => onPick(r)}>
          选择
        </Button>
      ),
    },
  ];

  return (
    <Drawer title={title} width={720} open={open} onClose={onClose} destroyOnClose>
      <Space style={{ marginBottom: 16 }} wrap>
        {toolbar({ resetPage: () => setPage(1) })}
      </Space>
      {loadError && !rows.length ? (
        <ListErrorState onRetry={load} />
      ) : (
        <Table<T>
          rowKey={rowKey}
          size="small"
          columns={allColumns}
          dataSource={rows}
          loading={loading}
          scroll={{ x: scrollX }}
          locale={{ emptyText }}
          pagination={pagination}
        />
      )}
    </Drawer>
  );
}
