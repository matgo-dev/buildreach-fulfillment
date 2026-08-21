"use client";
import { useCallback, useEffect, useState } from "react";
import { App, Button, Input, Modal, Segmented, Select, Space, Table } from "antd";
import { CheckOutlined, DeleteOutlined, RedoOutlined, StopOutlined } from "@ant-design/icons";
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
  type CustomerCreditMemoDetailOut,
  type CustomerCreditMemoOut,
  type CustomerCreditMemoStatus,
} from "@/lib/customerCreditMemo";

const STATUS_TABS = [
  { label: "全部", value: "" },
  { label: CUSTOMER_CREDIT_MEMO_STATUS_META.PENDING_APPROVAL.label, value: "PENDING_APPROVAL" },
  { label: CUSTOMER_CREDIT_MEMO_STATUS_META.POSTED.label, value: "POSTED" },
  { label: CUSTOMER_CREDIT_MEMO_STATUS_META.REJECTED.label, value: "REJECTED" },
  { label: CUSTOMER_CREDIT_MEMO_STATUS_META.VOIDED.label, value: "VOIDED" },
];

export default function CustomerCreditMemoPage() {
  const { message } = App.useApp();
  const [status, setStatus] = useState("");
  const [customerId, setCustomerId] = useState<number | undefined>(undefined);
  const [customers, setCustomers] = useState<CustomerListItem[]>([]);
  const [actingKey, setActingKey] = useState<string | null>(null);
  const [detailById, setDetailById] = useState<Record<number, CustomerCreditMemoDetailOut>>({});
  const [detailLoadingId, setDetailLoadingId] = useState<number | null>(null);
  const [rejectTarget, setRejectTarget] = useState<CustomerCreditMemoOut | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [resubmitTarget, setResubmitTarget] = useState<CustomerCreditMemoOut | null>(null);
  const [resubmitAmount, setResubmitAmount] = useState("");
  const [resubmitReason, setResubmitReason] = useState("");
  const [voidTarget, setVoidTarget] = useState<CustomerCreditMemoOut | null>(null);
  const [voidReason, setVoidReason] = useState("");

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

  async function act(key: string, fn: () => Promise<unknown>, ok: string) {
    setActingKey(key);
    try {
      await fn();
      message.success(ok);
      load();
    } catch (e) {
      message.error(resolveBizError(e, "操作失败"));
    } finally {
      setActingKey(null);
    }
  }

  async function loadDetail(id: number) {
    if (detailById[id]) return;
    setDetailLoadingId(id);
    try {
      const detail = await customerCreditMemoApi.get(id);
      setDetailById((prev) => ({ ...prev, [id]: detail }));
    } catch (e) {
      message.error(resolveBizError(e, "加载客户余额贷项单详情失败"));
    } finally {
      setDetailLoadingId(null);
    }
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
        <Space>
          <Can perm={Permissions.CUSTOMER_CREDIT_POST} fallback={null}>
            <Space>
              {row.status === "PENDING_APPROVAL" ? (
                <>
                  <Button
                    size="small"
                    icon={<CheckOutlined />}
                    loading={actingKey === `${row.id}:post`}
                    onClick={() => act(
                      `${row.id}:post`,
                      () => customerCreditMemoApi.post(row.id),
                      "客户余额贷项单已过账",
                    )}
                  >
                    过账
                  </Button>
                  <Button
                    size="small"
                    danger
                    icon={<StopOutlined />}
                    loading={actingKey === `${row.id}:reject`}
                    onClick={() => {
                      setRejectTarget(row);
                      setRejectReason("");
                    }}
                  >
                    驳回
                  </Button>
                </>
              ) : null}
            </Space>
          </Can>
          <Can perm={Permissions.CUSTOMER_CREDIT_CREATE} fallback={null}>
            {row.status === "REJECTED" ? (
              <Button
                size="small"
                icon={<RedoOutlined />}
                loading={actingKey === `${row.id}:resubmit`}
                onClick={() => {
                  setResubmitTarget(row);
                  setResubmitAmount(String(row.amount));
                  setResubmitReason(row.reason || "");
                }}
              >
                重提
              </Button>
            ) : null}
          </Can>
          <Can perm={Permissions.CUSTOMER_CREDIT_VOID} fallback={null}>
            {row.status === "POSTED" && Number(row.amount_allocated) === 0 ? (
              <Button
                size="small"
                danger
                icon={<DeleteOutlined />}
                loading={actingKey === `${row.id}:void`}
                onClick={() => {
                  setVoidTarget(row);
                  setVoidReason("");
                }}
              >
                作废
              </Button>
            ) : null}
          </Can>
        </Space>
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
              onExpand: (expanded, row) => {
                if (expanded) void loadDetail(row.id);
              },
              expandedRowRender: (row) => (
                <Table
                  size="small"
                  rowKey={(item, index) => `${item.label}-${index ?? 0}`}
                  pagination={false}
                  loading={detailLoadingId === row.id}
                  columns={[
                    { title: "内容", dataIndex: "label", width: 140 },
                    { title: "值", dataIndex: "value" },
                  ]}
                  dataSource={[
                    { label: "原因", value: row.reason || "—" },
                    { label: "驳回原因", value: row.reject_reason || "—" },
                    { label: "过账时间", value: row.posted_at ? formatDateTime(row.posted_at) : "—" },
                    { label: "作废原因", value: row.void_reason || "—" },
                    { label: "重提交来源", value: row.resubmitted_from_id || "—" },
                    ...(detailById[row.id]?.allocations || []).map((a) => ({
                      id: `alloc-${a.id}`,
                      label: "抵扣记录",
                      value: `${a.account_no} · ${formatMoney(a.amount)} CNY · ${
                        a.alloc_type === "AUTO" ? "自动" : "人工"
                      }`,
                    })),
                  ]}
                />
              ),
            }}
          />
        )}
      </ListPageBody>
      <Modal
        title="驳回客户余额贷项单"
        open={!!rejectTarget}
        okText="驳回"
        okButtonProps={{
          danger: true,
          disabled: !rejectReason.trim(),
          loading: actingKey === `${rejectTarget?.id}:reject`,
        }}
        cancelText="取消"
        onCancel={() => setRejectTarget(null)}
        onOk={() => rejectTarget && act(
          `${rejectTarget.id}:reject`,
          () => customerCreditMemoApi.reject(rejectTarget.id, rejectReason.trim()),
          "客户余额贷项单已驳回",
        ).then(() => setRejectTarget(null))}
      >
        <Input.TextArea
          rows={4}
          value={rejectReason}
          maxLength={500}
          showCount
          onChange={(e) => setRejectReason(e.target.value)}
          placeholder="驳回原因"
        />
      </Modal>
      <Modal
        title="重新提交客户余额贷项单"
        open={!!resubmitTarget}
        okText="提交"
        okButtonProps={{
          disabled: !resubmitAmount,
          loading: actingKey === `${resubmitTarget?.id}:resubmit`,
        }}
        cancelText="取消"
        onCancel={() => setResubmitTarget(null)}
        onOk={() => resubmitTarget && act(
          `${resubmitTarget.id}:resubmit`,
          () => customerCreditMemoApi.resubmit(resubmitTarget.id, {
            amount: resubmitAmount,
            reason: resubmitReason || null,
          }),
          "客户余额贷项单已重新提交",
        ).then(() => setResubmitTarget(null))}
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Input
            value={resubmitAmount}
            onChange={(e) => setResubmitAmount(e.target.value)}
            placeholder="金额"
          />
          <Input.TextArea
            rows={4}
            value={resubmitReason}
            maxLength={500}
            showCount
            onChange={(e) => setResubmitReason(e.target.value)}
            placeholder="原因"
          />
        </Space>
      </Modal>
      <Modal
        title="作废客户余额贷项单"
        open={!!voidTarget}
        okText="作废"
        okButtonProps={{ danger: true, loading: actingKey === `${voidTarget?.id}:void` }}
        cancelText="取消"
        onCancel={() => setVoidTarget(null)}
        onOk={() => voidTarget && act(
          `${voidTarget.id}:void`,
          () => customerCreditMemoApi.void(voidTarget.id, voidReason || null),
          "客户余额贷项单已作废",
        ).then(() => setVoidTarget(null))}
      >
        <Input.TextArea
          rows={4}
          value={voidReason}
          maxLength={500}
          showCount
          onChange={(e) => setVoidReason(e.target.value)}
          placeholder="作废原因"
        />
      </Modal>
    </ListPageCard>
  );
}
