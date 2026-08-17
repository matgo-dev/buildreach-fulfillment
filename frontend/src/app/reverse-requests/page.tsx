"use client";
import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Empty, Input, Segmented, Space } from "antd";
import type { ColumnsType } from "antd/es/table";
import { StatusTag } from "@/components/common/StatusTag";
import { ListErrorState } from "@/components/common/ListErrorState";
import { ListPageBody, ListPageCard } from "@/components/common/ListPageCard";
import { ListTable } from "@/components/common/ListTable";
import { Can } from "@/components/common/Can";
import { Permissions } from "@/config/permission-matrix";
import { useListQuery } from "@/hooks/useListQuery";
import { formatDateTime, formatQty } from "@/lib/format";
import { reverseRequestApi, type ReverseRequestListItem } from "@/lib/reverseRequest";
import {
  REVERSE_GOODS_STATUS_META,
  REVERSE_REQUEST_STATUS_META,
  REVERSE_SUPPLIER_RESOLUTION_LABEL,
} from "@/lib/reverseRequestStatus";

const STATUS_TABS = [
  { label: "全部", value: "" },
  { label: "待审核", value: "PENDING_REVIEW" },
  { label: "待处置", value: "APPROVED" },
  { label: "已驳回", value: "REJECTED" },
  { label: "已关闭", value: "COMPLETED" },
];

export default function ReverseRequestListPage() {
  const router = useRouter();
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");

  const fetcher = useCallback(
    ({ page, size }: { page: number; size: number }) =>
      reverseRequestApi.list({ status: status || undefined, q: q || undefined, page, size }),
    [status, q],
  );
  const { rows, setPage, loading, loadError, load, pagination } =
    useListQuery<ReverseRequestListItem>(fetcher, { errorMessage: "加载逆向申请失败" });

  const columns: ColumnsType<ReverseRequestListItem> = [
    { title: "申请单号", dataIndex: "no", width: 150 },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (s: ReverseRequestListItem["status"]) => (
        <StatusTag meta={REVERSE_REQUEST_STATUS_META} value={s} />
      ),
    },
    {
      title: "销售单",
      dataIndex: "sales_order_no",
      width: 150,
      render: (v: string, r) => (
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
    { title: "客户", dataIndex: "customer_display", width: 160, ellipsis: true },
    {
      title: "采购单 / 入库单",
      key: "source",
      width: 250,
      render: (_, r) => (
        <Space size={8} wrap>
          <Can perm={Permissions.PURCHASE_READ} fallback={<span>{r.purchase_order_no}</span>}>
            <Button
              type="link"
              size="small"
              style={{ padding: 0 }}
              onClick={(e) => {
                e.stopPropagation();
                router.push(`/purchasing/orders/${r.purchase_order_id}`);
              }}
            >
              {r.purchase_order_no}
            </Button>
          </Can>
          <Can perm={Permissions.INBOUND_READ} fallback={<span>{r.inbound_order_no}</span>}>
            <Button
              type="link"
              size="small"
              style={{ padding: 0 }}
              onClick={(e) => {
                e.stopPropagation();
                router.push(`/inbound/${r.inbound_order_id}`);
              }}
            >
              {r.inbound_order_no}
            </Button>
          </Can>
        </Space>
      ),
    },
    { title: "供应商", dataIndex: "supplier_display", width: 160, ellipsis: true },
    {
      title: "实物状态",
      dataIndex: "goods_status",
      width: 100,
      render: (s: ReverseRequestListItem["goods_status"]) => (
        <StatusTag meta={REVERSE_GOODS_STATUS_META} value={s} />
      ),
    },
    {
      title: "处理结论",
      dataIndex: "supplier_resolution",
      width: 170,
      render: (v: ReverseRequestListItem["supplier_resolution"]) =>
        v ? REVERSE_SUPPLIER_RESOLUTION_LABEL[v] : "—",
    },
    {
      title: "行数 / 数量",
      key: "qty",
      width: 120,
      align: "right",
      render: (_, r) => `${r.line_count} / ${formatQty(r.total_qty)}`,
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 170,
      render: (v: string) => formatDateTime(v),
    },
  ];

  return (
    <ListPageCard>
      <Space style={{ marginBottom: 16, width: "100%", justifyContent: "space-between" }} wrap>
        <Space wrap>
          <Segmented
            options={STATUS_TABS}
            value={status}
            onChange={(v) => {
              setStatus(v as string);
              setPage(1);
            }}
          />
          <Input.Search
            allowClear
            placeholder="申请单 / 销售单 / 采购单 / 入库单"
            style={{ width: 320 }}
            defaultValue={q}
            onSearch={(v) => {
              setQ(v.trim());
              setPage(1);
            }}
          />
        </Space>
      </Space>
      <ListPageBody>
        {loadError && !rows.length ? (
          <ListErrorState onRetry={load} />
        ) : (
          <ListTable<ReverseRequestListItem>
            rowKey="id"
            columns={columns}
            dataSource={rows}
            loading={loading}
            scroll={{ x: 1520 }}
            locale={{ emptyText: <Empty description="暂无逆向申请" /> }}
            onRow={(r) => ({
              onClick: () => router.push(`/reverse-requests/${r.id}`),
              style: { cursor: "pointer" },
            })}
            pagination={pagination}
          />
        )}
      </ListPageBody>
    </ListPageCard>
  );
}
