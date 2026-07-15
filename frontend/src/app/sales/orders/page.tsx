"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { App, Card, Segmented, Space, Switch, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useAuthStore } from "@/stores/authStore";
import { salesOrderApi, type SalesOrderListItem } from "@/lib/salesOrder";
import { SALES_ORDER_STATUS_META } from "@/lib/salesOrderStatus";

// 本增量销售单只建初始态,故状态筛选暂只「全部/已确认」;转采购增量扩态后再补。
const STATUS_TABS = [
  { label: "全部", value: "" },
  { label: "已确认", value: "CONFIRMED" },
];

export default function SalesOrderListPage() {
  const router = useRouter();
  const { message } = App.useApp();
  const userId = useAuthStore((s) => s.user?.id);

  const [rows, setRows] = useState<SalesOrderListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [mineOnly, setMineOnly] = useState(false);
  const [sort, setSort] = useState<"created_at" | "total_amount">("created_at");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await salesOrderApi.list({
        status: status || undefined,
        salesperson_id: mineOnly && userId ? userId : undefined,
        sort,
        page,
        size: 20,
      });
      setRows(res.items);
      setTotal(res.total);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "加载销售单列表失败");
    } finally {
      setLoading(false);
    }
  }, [status, mineOnly, userId, sort, page, message]);

  useEffect(() => {
    load();
  }, [load]);

  const columns: ColumnsType<SalesOrderListItem> = [
    { title: "单号", dataIndex: "no", width: 150 },
    { title: "客户", dataIndex: "customer_display", width: 160, ellipsis: true },
    { title: "报价人", dataIndex: "salesperson_display", width: 100 },
    {
      title: "状态",
      dataIndex: "status",
      width: 110,
      render: (s: SalesOrderListItem["status"]) => {
        const m = SALES_ORDER_STATUS_META[s];
        return <Tag color={m.color}>{m.label}</Tag>;
      },
    },
    { title: "币种", dataIndex: "currency", width: 70 },
    {
      title: "总额",
      dataIndex: "total_amount",
      width: 120,
      align: "right",
      sorter: true,
      render: (v) => Number(v).toLocaleString(undefined, { minimumFractionDigits: 2 }),
    },
    { title: "行数", dataIndex: "line_count", width: 70, align: "right" },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 170,
      render: (v: string) => v?.replace("T", " ").slice(0, 16),
    },
  ];

  return (
    <Card>
      <Space style={{ marginBottom: 16, width: "100%" }} wrap>
        <Segmented
          options={STATUS_TABS}
          value={status}
          onChange={(v) => {
            setStatus(v as string);
            setPage(1);
          }}
        />
        <span>
          <Switch
            size="small"
            checked={mineOnly}
            onChange={(c) => {
              setMineOnly(c);
              setPage(1);
            }}
          />{" "}
          报价人=我
        </span>
      </Space>
      <Table<SalesOrderListItem>
        rowKey="id"
        columns={columns}
        dataSource={rows}
        loading={loading}
        scroll={{ x: 1000 }}
        locale={{ emptyText: "暂无销售单" }}
        onRow={(r) => ({
          onClick: () => router.push(`/sales/orders/${r.id}`),
          style: { cursor: "pointer" },
        })}
        pagination={{
          current: page,
          total,
          pageSize: 20,
          showSizeChanger: false,
          showTotal: (t) => `共 ${t} 条`,
          onChange: setPage,
        }}
        onChange={(_p, _f, sorter) => {
          const s = Array.isArray(sorter) ? sorter[0] : sorter;
          setSort(s?.field === "total_amount" ? "total_amount" : "created_at");
        }}
      />
    </Card>
  );
}
