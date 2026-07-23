"use client";
import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Empty, Input, Segmented, Space } from "antd";
import { ContainerOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { Can } from "@/components/common/Can";
import { StatusTag } from "@/components/common/StatusTag";
import { ListTable } from "@/components/common/ListTable";
import { ListErrorState } from "@/components/common/ListErrorState";
import { ListPageCard, ListPageBody } from "@/components/common/ListPageCard";
import { useListQuery } from "@/hooks/useListQuery";
import { Permissions } from "@/config/permission-matrix";
import { formatDateTime, formatQty } from "@/lib/format";
import { outboundOrderApi, type OutboundOrderListItem } from "@/lib/outboundOrder";
import { OUTBOUND_ORDER_STATUS_META } from "@/lib/outboundOrderStatus";

const STATUS_TABS = [
  { label: "全部", value: "" },
  { label: "草稿", value: "DRAFT" },
  { label: "已出库", value: "ISSUED" },
  { label: "已取消", value: "CANCELLED" },
];

export default function OutboundOrderListPage() {
  const router = useRouter();

  const [status, setStatus] = useState("");
  const [keyword, setKeyword] = useState("");

  const fetcher = useCallback(
    ({ page, size }: { page: number; size: number }) =>
      outboundOrderApi.list({
        status: status || undefined,
        keyword: keyword || undefined,
        page,
        size,
      }),
    [status, keyword],
  );
  const { rows, setPage, loading, loadError, load, pagination } =
    useListQuery<OutboundOrderListItem>(fetcher, { errorMessage: "加载出库单列表失败" });

  // 出库单据零售价/零成本列(契约 §3):列表无任何金额列。
  const columns: ColumnsType<OutboundOrderListItem> = [
    { title: "出库单号", dataIndex: "no", width: 160 },
    {
      // 来源销售单:有 sales:read 即可点击跳销售单详情,无权限降级纯文本(DESIGN §7)。
      // 行本身点击进出库详情,故 SO 链接需 stopPropagation 阻止冒泡。
      title: "销售单号",
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
    {
      // 关联发运柜:有 shipment:read 即可点击跳柜工作台,无权限降级纯文本。
      title: "发运柜",
      dataIndex: "shipment_no",
      width: 170,
      render: (v: string | null, r) => {
        const label = r.container_no || v || "—";
        if (!v) return label;
        return (
          <Can perm={Permissions.SHIPMENT_READ} fallback={<span>{label}</span>}>
            <Button
              type="link"
              size="small"
              style={{ padding: 0 }}
              onClick={(e) => {
                e.stopPropagation();
                router.push(`/shipments/${r.shipment_id}`);
              }}
            >
              {label}
            </Button>
          </Can>
        );
      },
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (s: OutboundOrderListItem["status"]) => (
        <StatusTag meta={OUTBOUND_ORDER_STATUS_META} value={s} />
      ),
    },
    {
      title: "行数 / 件数",
      key: "qty",
      width: 120,
      align: "right",
      render: (_, r) => `${r.line_count} / ${formatQty(r.total_qty)}`,
    },
    {
      title: "确认时间",
      dataIndex: "issued_at",
      width: 170,
      render: (v: string | null) => (v ? formatDateTime(v) : "—"),
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
      {/* 工具条统一次序(DESIGN §7):状态 → 搜索(覆盖 单号/SO号/柜号)。 */}
      <Space style={{ marginBottom: 16 }} wrap>
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
          placeholder="出库单号 / 销售单号 / 柜号"
          style={{ width: 280 }}
          defaultValue={keyword}
          onSearch={(v) => {
            setKeyword(v.trim());
            setPage(1);
          }}
        />
      </Space>

      <ListPageBody>
        {loadError && !rows.length ? (
          <ListErrorState onRetry={load} />
        ) : (
          <ListTable<OutboundOrderListItem>
            rowKey="id"
            columns={columns}
            dataSource={rows}
            loading={loading}
            scroll={{ x: 1040 }}
            locale={{
              emptyText: (
                // 出库单在柜工作台内组柜生成,故空态引导去发运柜(需 shipment:manage 才显按钮)。
                <Empty description="暂无出库单">
                  <Can perm={Permissions.SHIPMENT_MANAGE}>
                    <Button
                      type="primary"
                      icon={<ContainerOutlined />}
                      onClick={() => router.push("/shipments")}
                    >
                      去发运柜组柜
                    </Button>
                  </Can>
                </Empty>
              ),
            }}
            onRow={(r) => ({
              onClick: () => router.push(`/outbound/${r.id}`),
              style: { cursor: "pointer" },
            })}
            pagination={pagination}
          />
        )}
      </ListPageBody>
    </ListPageCard>
  );
}
