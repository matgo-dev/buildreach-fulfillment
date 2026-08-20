"use client";
import { useCallback, useEffect, useState } from "react";
import { App, Button, Input, Segmented, Select, Space, Table } from "antd";
import { CheckOutlined, RedoOutlined, StopOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { Can } from "@/components/common/Can";
import { StatusTag } from "@/components/common/StatusTag";
import { ListTable } from "@/components/common/ListTable";
import { ListErrorState } from "@/components/common/ListErrorState";
import { ListPageCard, ListPageBody } from "@/components/common/ListPageCard";
import { useListQuery } from "@/hooks/useListQuery";
import { Permissions } from "@/config/permission-matrix";
import { customerApi, type CustomerListItem } from "@/lib/customer";
import { formatDateTime, formatMoney } from "@/lib/format";
import { resolveBizError } from "@/lib/errorMessages";
import {
  CUSTOMER_CREDIT_MEMO_STATUS_META,
  customerCreditMemoApi,
  type CustomerCreditMemoOut,
  type CustomerCreditMemoStatus,
} from "@/lib/customerCreditMemo";

const STATUS_TABS = [
  { label: "全部", value: "" },
  { label: CUSTOMER_CREDIT_MEMO_STATUS_META.PENDING_APPROVAL.label, value: "PENDING_APPROVAL" },
  { label: CUSTOMER_CREDIT_MEMO_STATUS_META.POSTED.label, value: "POSTED" },
  { label: CUSTOMER_CREDIT_MEMO_STATUS_META.REJECTED.label, value: "REJECTED" },
];

export default function CustomerCreditMemoPage() {
  const { message, modal } = App.useApp();
  const [status, setStatus] = useState("");
  const [customerId, setCustomerId] = useState<number | undefined>(undefined);
  const [customers, setCustomers] = useState<CustomerListItem[]>([]);
  const [acting, setActing] = useState(false);

  const fetcher = useCallback(
    ({ page, size }: { page: number; size: number }) =>
      customerCreditMemoApi.list({
        status: (status || undefined) as CustomerCreditMemoStatus | undefined,
        customer_id: customerId,
        page,
        size,
      }),
    [status, customerId],
  );
  const { rows, setPage, loading, loadError, load, pagination } = useListQuery<CustomerCreditMemoOut>(
    fetcher,
    { errorMessage: "加载客户余额贷项单失败" },
  );

  useEffect(() => {
    customerApi
      .list({ size: 100 })
      .then((res) => setCustomers(res.items))
      .catch(() => undefined);
  }, []);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setActing(true);
    try {
      await fn();
      message.success(ok);
      load();
    } catch (e) {
      message.error(resolveBizError(e, "操作失败"));
    } finally {
      setActing(false);
    }
  }

  function rejectMemo(id: number) {
    modal.confirm({
      title: "驳回客户余额贷项单",
      okText: "驳回",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: () => act(() => customerCreditMemoApi.reject(id), "客户余额贷项单已驳回"),
    });
  }

  const columns: ColumnsType<CustomerCreditMemoOut> = [
    { title: "贷项单号", dataIndex: "no", width: 170 },
    {
      title: "客户",
      dataIndex: "customer_id",
      width: 180,
      render: (id: number) => customers.find((c) => c.id === id)?.name || id,
    },
    { title: "销售单 ID", dataIndex: "sales_order_id", width: 110 },
    { title: "库存处置 ID", dataIndex: "inventory_disposition_order_id", width: 120 },
    {
      title: "金额",
      dataIndex: "amount",
      width: 130,
      align: "right",
      render: (v) => <span style={{ fontWeight: 600 }}>{formatMoney(v)} CNY</span>,
    },
    {
      title: "未分配余额",
      dataIndex: "amount_unallocated",
      width: 140,
      align: "right",
      render: (v, r) => r.status === "POSTED" ? formatMoney(v) : "—",
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 130,
      render: (s: CustomerCreditMemoStatus) => (
        <StatusTag meta={CUSTOMER_CREDIT_MEMO_STATUS_META} value={s} />
      ),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 170,
      render: (v: string) => formatDateTime(v),
    },
    {
      title: "操作",
      key: "actions",
      width: 230,
      fixed: "right",
      render: (_, row) => (
        <Can perm={Permissions.RECEIPT_MANAGE} fallback={null}>
          <Space>
            {row.status === "PENDING_APPROVAL" ? (
              <>
                <Button
                  size="small"
                  icon={<CheckOutlined />}
                  loading={acting}
                  onClick={() => act(() => customerCreditMemoApi.post(row.id), "客户余额贷项单已过账")}
                >
                  过账
                </Button>
                <Button
                  size="small"
                  danger
                  icon={<StopOutlined />}
                  loading={acting}
                  onClick={() => rejectMemo(row.id)}
                >
                  驳回
                </Button>
              </>
            ) : null}
            {row.status === "REJECTED" ? (
              <Button
                size="small"
                icon={<RedoOutlined />}
                loading={acting}
                onClick={() => act(() => customerCreditMemoApi.resubmit(row.id), "客户余额贷项单已重新提交")}
              >
                重提
              </Button>
            ) : null}
          </Space>
        </Can>
      ),
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
          <Select
            allowClear
            showSearch
            placeholder="客户"
            optionFilterProp="label"
            style={{ width: 240 }}
            value={customerId}
            onChange={(v) => {
              setCustomerId(v);
              setPage(1);
            }}
            options={customers.map((c) => ({ value: c.id, label: `${c.code} · ${c.name}` }))}
          />
        </Space>
        <Input disabled value="CNY" style={{ width: 84 }} aria-label="币种" />
      </Space>

      <ListPageBody>
        {loadError && !rows.length ? (
          <ListErrorState onRetry={load} />
        ) : (
          <ListTable<CustomerCreditMemoOut>
            rowKey="id"
            columns={columns}
            dataSource={rows}
            loading={loading}
            pagination={pagination}
            scroll={{ x: 1250 }}
            locale={{ emptyText: "暂无客户余额贷项单" }}
            expandable={{
              expandedRowRender: (row) => (
                <Table
                  size="small"
                  rowKey="label"
                  pagination={false}
                  columns={[
                    { title: "字段", dataIndex: "label", width: 140 },
                    { title: "内容", dataIndex: "value" },
                  ]}
                  dataSource={[
                    { label: "原因", value: row.reason || "—" },
                    { label: "驳回原因", value: row.reject_reason || "—" },
                    { label: "过账时间", value: row.posted_at ? formatDateTime(row.posted_at) : "—" },
                  ]}
                />
              ),
            }}
          />
        )}
      </ListPageBody>
    </ListPageCard>
  );
}
