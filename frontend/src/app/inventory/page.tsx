"use client";
import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Empty, Input, Space, Switch, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Can } from "@/components/common/Can";
import { ListTable } from "@/components/common/ListTable";
import { ListErrorState } from "@/components/common/ListErrorState";
import { NumCell } from "@/components/common/NumCell";
import { ListPageCard, ListPageBody } from "@/components/common/ListPageCard";
import { useListQuery } from "@/hooks/useListQuery";
import { Permissions } from "@/config/permission-matrix";
import { inventoryApi, type StockBalanceItem } from "@/lib/inventory";

export default function InventoryListPage() {
  const router = useRouter();

  const [keyword, setKeyword] = useState("");
  // 含已发完行:关(默认)= available>0 在库视角;开 = scope=history(inbound>0 OR outbound>0,
  // 履约史)——相对默认视图的增量只有「已全部发完」的行;未入库行按契约 §2/§5 不进本页
  // (其对照视图在 SO 详情 stock_balances 块,内部 ALL 口径)。
  const [includeHistory, setIncludeHistory] = useState(false);

  const fetcher = useCallback(
    ({ page, size }: { page: number; size: number }) =>
      inventoryApi.list({
        q: keyword || undefined,
        scope: includeHistory ? "history" : undefined,
        page,
        size,
      }),
    [keyword, includeHistory],
  );
  const { rows, setPage, loading, loadError, load, pagination } = useListQuery<StockBalanceItem>(fetcher, {
    errorMessage: "加载库存列表失败",
  });

  const columns: ColumnsType<StockBalanceItem> = [
    {
      title: "销售单号",
      dataIndex: "sales_order_no",
      width: 150,
      render: (v: string, r) => (
        // 单据链接降级(DESIGN §7):无 sales:read 时降级纯文本,不点撞 403。
        <Can perm={Permissions.SALES_READ} fallback={<span>{v}</span>}>
          <Button
            type="link"
            size="small"
            style={{ padding: 0 }}
            onClick={(e) => {
              e.stopPropagation();
              router.push(`/sales/orders/${r.sales_order_id}`);
            }}
          >
            {v}
          </Button>
        </Can>
      ),
    },
    { title: "SKU编码", dataIndex: "sku_code", width: 140 },
    { title: "品名", dataIndex: "name", ellipsis: true },
    { title: "规格", dataIndex: "spec_text", ellipsis: true, render: (v) => v || "—" },
    { title: "单位", dataIndex: "unit", width: 70 },
    {
      title: "订购量",
      dataIndex: "ordered_qty",
      width: 100,
      align: "right",
      render: (v: number | string) => <NumCell value={v} />,
    },
    {
      title: "已入库",
      dataIndex: "inbound_qty",
      width: 100,
      align: "right",
      render: (v: number | string) => <NumCell value={v} />,
    },
    {
      title: "已出库",
      dataIndex: "outbound_qty",
      width: 100,
      align: "right",
      render: (v: number | string) => <NumCell value={v} />,
    },
    {
      title: "可发量",
      dataIndex: "available_qty",
      width: 100,
      align: "right",
      render: (v: number | string) => <NumCell value={v} strong />,
    },
  ];

  return (
    <ListPageCard>
      {/* 工具条统一次序(DESIGN §7):无状态轴 → 搜索 → 页面特有开关。 */}
      <Space style={{ marginBottom: 16, width: "100%", justifyContent: "space-between" }} wrap>
        <Space wrap>
          <Input.Search
            allowClear
            placeholder="销售单号 / SKU编码 / 品名"
            style={{ width: 280 }}
            defaultValue={keyword}
            onSearch={(v) => {
              setKeyword(v.trim());
              setPage(1);
            }}
          />
          <span>
            <Switch
              size="small"
              checked={includeHistory}
              onChange={(c) => {
                setIncludeHistory(c);
                setPage(1);
              }}
            />{" "}
            <Tooltip title="同时显示货已全部发完(可发量归 0)的历史行;尚未入库的行不在本页,见销售单详情">
              含已发完行
            </Tooltip>
          </span>
        </Space>
      </Space>

      <ListPageBody>
        {loadError && !rows.length ? (
          <ListErrorState onRetry={load} />
        ) : (
          <ListTable<StockBalanceItem>
            rowKey={(r) => `${r.sales_order_id}-${r.sku_code}`}
            columns={columns}
            dataSource={rows}
            loading={loading}
            scroll={{ x: 1000 }}
            locale={{
              emptyText: <Empty description="暂无在库货品" />,
            }}
            pagination={pagination}
          />
        )}
      </ListPageBody>
    </ListPageCard>
  );
}
