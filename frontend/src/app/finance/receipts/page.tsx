"use client";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  App,
  Button,
  Card,
  DatePicker,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { Can } from "@/components/common/Can";
import { StatusTag } from "@/components/common/StatusTag";
import { ListErrorState } from "@/components/common/ListErrorState";
import { useListQuery } from "@/hooks/useListQuery";
import { Permissions } from "@/config/permission-matrix";
import { customerApi, type CustomerListItem } from "@/lib/customer";
import { formatDateTime, formatMoney } from "@/lib/format";
import { resolveBizError } from "@/lib/errorMessages";
import {
  RECEIPT_STATUS_META,
  receiptApi,
  type ReceiptDetail,
  type ReceiptListItem,
  type ReceiptStatusFilter,
} from "@/lib/receipt";
import { receivableApi, type ReceivableListItem } from "@/lib/receivable";
import { CURRENCIES } from "@/lib/currencies";

// 状态 tabs:全部 + 四派生态 + 作废(VOIDED 显式查作废行,单一源头 RECEIPT_STATUS_META + VOIDED)。
const STATUS_TABS = [
  { label: "全部", value: "" },
  ...Object.entries(RECEIPT_STATUS_META).map(([v, m]) => ({ label: m.label, value: v })),
  { label: "已作废", value: "VOIDED" },
];

/** 单头/列表行状态徽标:作废优先显「已作废」,否则走派生态映射。 */
function ReceiptStatusTag({ status, voidedAt }: { status: string; voidedAt: string | null }) {
  if (voidedAt) return <Tag>已作废</Tag>;
  return <StatusTag meta={RECEIPT_STATUS_META} value={status} />;
}

export default function ReceiptListPage() {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  // D10 一键入口:从应收抽屉带 customer_id 预筛进来(useSearchParams,与 /purchasing/orders 同式)。
  const presetCustomerId = useSearchParams().get("customer_id");

  const [status, setStatus] = useState("");
  const [keyword, setKeyword] = useState("");
  const [customerId, setCustomerId] = useState<number | undefined>(
    presetCustomerId ? Number(presetCustomerId) : undefined,
  );
  const [currency, setCurrency] = useState<string | undefined>(undefined);
  const [customers, setCustomers] = useState<CustomerListItem[]>([]);

  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);

  // 详情抽屉 + 行操作(认领 / 人工核销 / 作废 / 反核销)。
  const [detail, setDetail] = useState<ReceiptDetail | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [acting, setActing] = useState(false);

  const [claimOpen, setClaimOpen] = useState(false);
  const [claimCustomerId, setClaimCustomerId] = useState<number | undefined>(undefined);

  const [allocOpen, setAllocOpen] = useState(false);
  const [allocAccountId, setAllocAccountId] = useState<number | undefined>(undefined);
  const [candidates, setCandidates] = useState<ReceivableListItem[]>([]);
  const [candLoading, setCandLoading] = useState(false);

  const [voidOpen, setVoidOpen] = useState(false);
  const [voidReason, setVoidReason] = useState("");

  const [reverseAllocId, setReverseAllocId] = useState<number | null>(null);
  const [reverseReason, setReverseReason] = useState("");

  const fetcher = useCallback(
    ({ page, size }: { page: number; size: number }) =>
      receiptApi.list({
        customer_id: customerId,
        currency: currency || undefined,
        status: (status || undefined) as ReceiptStatusFilter | undefined,
        q: keyword.trim() || undefined,
        page,
        size,
      }),
    [customerId, currency, status, keyword],
  );
  const { rows, setPage, loading, loadError, load, pagination } = useListQuery<ReceiptListItem>(
    fetcher,
    { errorMessage: "加载收款单列表失败" },
  );

  // 客户下拉(筛选 + 认领共用)。
  useEffect(() => {
    customerApi
      .list({ size: 100 })
      .then((res) => setCustomers(res.items))
      .catch(() => undefined);
  }, []);

  async function openDetail(id: number) {
    setDetailOpen(true);
    setDetailLoading(true);
    setDetail(null);
    try {
      setDetail(await receiptApi.get(id));
    } catch (e) {
      message.error(resolveBizError(e, "加载收款单详情失败"));
      setDetailOpen(false);
    } finally {
      setDetailLoading(false);
    }
  }

  // 操作后:用返回的最新详情刷新抽屉 + 重拉列表(金额/状态派生已变)。
  function applyDetail(d: ReceiptDetail) {
    setDetail(d);
    load();
  }

  async function onCreate() {
    const v = await form.validateFields().catch(() => null);
    if (!v) return;
    setCreating(true);
    try {
      const d = await receiptApi.create({
        amount: String(v.amount),
        currency: v.currency,
        received_at: (v.received_at as dayjs.Dayjs).format("YYYY-MM-DD"),
        customer_id: v.customer_id ?? null,
        account_info: v.account_info?.trim() || null,
        note: v.note?.trim() || null,
      });
      message.success(`已登记收款 ${d.receipt.receipt_no}`);
      setCreateOpen(false);
      form.resetFields();
      load();
      openDetail(d.receipt.id);
    } catch (e) {
      message.error(resolveBizError(e, "登记失败"));
    } finally {
      setCreating(false);
    }
  }

  async function doClaim() {
    if (!detail || !claimCustomerId) return;
    setActing(true);
    try {
      applyDetail(await receiptApi.claim(detail.receipt.id, claimCustomerId));
      message.success("已认领客户");
      setClaimOpen(false);
      setClaimCustomerId(undefined);
    } catch (e) {
      message.error(resolveBizError(e, "认领失败"));
    } finally {
      setActing(false);
    }
  }

  async function openAllocate() {
    if (!detail?.receipt.customer_id) return;
    setAllocOpen(true);
    setAllocAccountId(undefined);
    setCandLoading(true);
    try {
      const res = await receivableApi.list({ customer_id: detail.receipt.customer_id, size: 100 });
      // 候选 = 未结清(非 PAID)且同币种(核销要求同币种)。
      setCandidates(
        res.items.filter(
          (r) => r.status !== "PAID" && r.currency === detail.receipt.currency,
        ),
      );
    } catch (e) {
      message.error(resolveBizError(e, "加载待核销应收失败"));
    } finally {
      setCandLoading(false);
    }
  }

  async function doAllocate() {
    if (!detail || !allocAccountId) return;
    setActing(true);
    try {
      applyDetail(await receiptApi.allocate(detail.receipt.id, allocAccountId));
      message.success("已核销");
      setAllocOpen(false);
    } catch (e) {
      message.error(resolveBizError(e, "核销失败"));
    } finally {
      setActing(false);
    }
  }

  async function doVoid() {
    if (!detail) return;
    setActing(true);
    try {
      applyDetail(await receiptApi.void(detail.receipt.id, voidReason.trim() || null));
      message.success("已作废");
      setVoidOpen(false);
      setVoidReason("");
    } catch (e) {
      message.error(resolveBizError(e, "作废失败"));
    } finally {
      setActing(false);
    }
  }

  async function doReverse() {
    if (reverseAllocId == null) return;
    setActing(true);
    try {
      applyDetail(await receiptApi.reverseAllocation(reverseAllocId, reverseReason.trim() || null));
      message.success("已反核销");
      setReverseAllocId(null);
      setReverseReason("");
    } catch (e) {
      message.error(resolveBizError(e, "反核销失败"));
    } finally {
      setActing(false);
    }
  }

  const columns: ColumnsType<ReceiptListItem> = [
    { title: "收款单号", dataIndex: "receipt_no", width: 170 },
    {
      title: "客户",
      dataIndex: "customer_display",
      width: 180,
      ellipsis: true,
      render: (v: string | null) => v || <Typography.Text type="warning">待认领</Typography.Text>,
    },
    {
      title: "币种",
      dataIndex: "currency",
      width: 90,
      // 次要枚举走列头筛选(DESIGN §7),服务端过滤;单选(核销要求同币种,多选无场景)。
      filters: CURRENCIES.map((c) => ({ text: c, value: c })),
      filterMultiple: false,
      filteredValue: currency ? [currency] : null,
    },
    {
      title: "金额",
      dataIndex: "amount",
      width: 130,
      align: "right",
      render: (v: number) => formatMoney(v),
    },
    {
      title: "已分配",
      dataIndex: "amount_allocated",
      width: 120,
      align: "right",
      render: (v: number) => formatMoney(v),
    },
    {
      title: "未分配",
      dataIndex: "amount_unallocated",
      width: 130,
      align: "right",
      render: (v: number) => <span style={{ fontWeight: 600 }}>{formatMoney(v)}</span>,
    },
    {
      title: "状态",
      key: "status",
      width: 110,
      render: (_, r) => <ReceiptStatusTag status={r.status} voidedAt={r.voided_at} />,
    },
    { title: "到账日", dataIndex: "received_at", width: 120 },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 170,
      render: (v: string) => formatDateTime(v),
    },
  ];

  const r = detail?.receipt;
  const canClaim = r && !r.voided_at && r.status === "UNCLAIMED";
  const canAllocate = r && !r.voided_at && r.status !== "UNCLAIMED" && r.amount_unallocated > 0;
  const canVoid = r && !r.voided_at;

  return (
    <Card>
      {/* 工具条统一次序(DESIGN §7):状态 Segmented → 搜索框 → 参照维度下拉。币种在列头。 */}
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
            placeholder="收款单号 / 客户名"
            allowClear
            style={{ width: 240 }}
            onSearch={(v) => {
              setKeyword(v);
              setPage(1);
            }}
          />
          <Select
            allowClear
            showSearch
            placeholder="客户"
            optionFilterProp="label"
            style={{ width: 220 }}
            value={customerId}
            onChange={(v) => {
              setCustomerId(v);
              setPage(1);
            }}
            options={customers.map((c) => ({ value: c.id, label: `${c.code} · ${c.name}` }))}
          />
        </Space>
        <Can perm={Permissions.RECEIPT_MANAGE}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            登记收款
          </Button>
        </Can>
      </Space>

      {loadError && !rows.length ? (
        <ListErrorState onRetry={load} />
      ) : (
        <Table<ReceiptListItem>
          rowKey="id"
          columns={columns}
          dataSource={rows}
          loading={loading}
          scroll={{ x: 1290 }}
          locale={{ emptyText: "暂无收款单" }}
          onChange={(_, filters) => {
            // 列头币种筛选 → 服务端过滤(filters.currency 单选)。
            const c = (filters.currency?.[0] as string) || undefined;
            if (c !== currency) {
              setCurrency(c);
              setPage(1);
            }
          }}
          onRow={(row) => ({
            onClick: () => openDetail(row.id),
            style: { cursor: "pointer" },
          })}
          pagination={pagination}
        />
      )}

      {/* 登记收款:amount/currency/received_at 必填;客户可留空=待认领。 */}
      <Modal
        title="登记收款"
        open={createOpen}
        okText="登记"
        confirmLoading={creating}
        onCancel={() => {
          setCreateOpen(false);
          form.resetFields();
        }}
        onOk={onCreate}
      >
        <Form
          form={form}
          layout="vertical"
          style={{ marginTop: 12 }}
          initialValues={{ currency: "USD", received_at: dayjs() }}
        >
          <Form.Item
            name="amount"
            label="到账金额"
            rules={[{ required: true, message: "请输入到账金额" }]}
          >
            {/* precision=2:两位小数与后端 Decimal(decimal_places=2)/DB Numeric(18,2) 对齐,禁三位小数被静默舍入。 */}
            <InputNumber min={0.01} step={0.01} precision={2} style={{ width: "100%" }} placeholder="登记即定死,> 0" />
          </Form.Item>
          <Form.Item name="currency" label="币种" rules={[{ required: true }]}>
            <Select options={CURRENCIES.map((c) => ({ value: c, label: c }))} />
          </Form.Item>
          <Form.Item name="received_at" label="到账日" rules={[{ required: true }]}>
            <DatePicker style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="customer_id" label="客户(可留空 = 待认领)">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="留空则登记为待认领,稍后认领"
              options={customers.map((c) => ({ value: c.id, label: `${c.code} · ${c.name}` }))}
            />
          </Form.Item>
          <Form.Item name="account_info" label="到账账户信息">
            <Input placeholder="选填,如银行流水摘要" maxLength={200} />
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input.TextArea rows={2} placeholder="选填" maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 详情抽屉:单头 + 未分配余额高亮 + 活动核销记录。 */}
      <Drawer
        title={r ? `收款单 ${r.receipt_no}` : "收款单详情"}
        width={640}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        loading={detailLoading}
        extra={
          r && (
            <Can perm={Permissions.RECEIPT_MANAGE}>
              <Space>
                {canClaim && <Button onClick={() => setClaimOpen(true)}>认领客户</Button>}
                {canAllocate && (
                  <Button type="primary" onClick={openAllocate}>
                    人工核销
                  </Button>
                )}
                {canVoid && (
                  <Button danger onClick={() => setVoidOpen(true)}>
                    作废
                  </Button>
                )}
              </Space>
            </Can>
          )
        }
      >
        {r && (
          <>
            {r.voided_at && (
              <Tag color="error" style={{ marginBottom: 12 }}>
                已作废{r.void_reason ? ` · ${r.void_reason}` : ""}
              </Tag>
            )}
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="客户">
                {r.customer_display || <Typography.Text type="warning">待认领</Typography.Text>}
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <ReceiptStatusTag status={r.status} voidedAt={r.voided_at} />
              </Descriptions.Item>
              <Descriptions.Item label="币种">{r.currency}</Descriptions.Item>
              <Descriptions.Item label="到账日">{r.received_at}</Descriptions.Item>
              <Descriptions.Item label="金额">
                {formatMoney(r.amount)} {r.currency}
              </Descriptions.Item>
              <Descriptions.Item label="已分配">
                {formatMoney(r.amount_allocated)} {r.currency}
              </Descriptions.Item>
              <Descriptions.Item label="未分配余额" span={2}>
                <Typography.Text strong type={r.amount_unallocated > 0 ? "success" : undefined}>
                  {formatMoney(r.amount_unallocated)} {r.currency}
                </Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label="到账账户" span={2}>
                {r.account_info || "—"}
              </Descriptions.Item>
              <Descriptions.Item label="备注" span={2}>
                {r.note || "—"}
              </Descriptions.Item>
            </Descriptions>

            <Typography.Title level={5} style={{ marginTop: 20 }}>
              核销记录
            </Typography.Title>
            <Table
              rowKey="id"
              size="small"
              dataSource={detail?.allocations}
              pagination={false}
              locale={{ emptyText: "暂无核销记录" }}
              columns={[
                { title: "冲销单据", dataIndex: "account_no", width: 160 },
                {
                  title: "金额",
                  dataIndex: "amount",
                  width: 120,
                  align: "right",
                  // D9:无 receivable:read 者应收额脱敏为 null,显「—」。
                  render: (v: number | null) => (v == null ? "—" : formatMoney(v)),
                },
                {
                  title: "类型",
                  dataIndex: "alloc_type",
                  width: 80,
                  render: (v: string) => (v === "AUTO" ? "自动" : "人工"),
                },
                {
                  title: "核销时间",
                  dataIndex: "created_at",
                  width: 150,
                  render: (v: string) => formatDateTime(v),
                },
                {
                  title: "操作",
                  key: "op",
                  width: 90,
                  render: (_, a) =>
                    r.voided_at ? null : (
                      <Can perm={Permissions.RECEIPT_MANAGE}>
                        <Button
                          type="link"
                          size="small"
                          danger
                          style={{ padding: 0 }}
                          onClick={() => {
                            setReverseAllocId(a.id);
                            setReverseReason("");
                          }}
                        >
                          反核销
                        </Button>
                      </Can>
                    ),
                },
              ]}
            />
          </>
        )}
      </Drawer>

      {/* 认领客户(仅 UNCLAIMED):认领后后端同事务自动核销该客户开口应收。 */}
      <Modal
        title="认领客户"
        open={claimOpen}
        okText="认领"
        okButtonProps={{ disabled: !claimCustomerId }}
        confirmLoading={acting}
        onCancel={() => setClaimOpen(false)}
        onOk={doClaim}
      >
        <Typography.Paragraph type="secondary">
          认领后将自动核销该客户未结清应收,请确认款项归属。
        </Typography.Paragraph>
        <Select
          showSearch
          optionFilterProp="label"
          style={{ width: "100%" }}
          placeholder="选择客户"
          value={claimCustomerId}
          onChange={setClaimCustomerId}
          options={customers.map((c) => ({ value: c.id, label: `${c.code} · ${c.name}` }))}
        />
      </Modal>

      {/* 人工核销:选一张未结清应收,金额由后端自动取满 min(不由前端填)。 */}
      <Modal
        title="人工核销"
        open={allocOpen}
        okText="核销"
        okButtonProps={{ disabled: !allocAccountId }}
        confirmLoading={acting}
        onCancel={() => setAllocOpen(false)}
        onOk={doAllocate}
      >
        <Typography.Paragraph type="secondary">
          核销金额自动取「未分配余额」与「应收余额」的较小值,无需填写。
        </Typography.Paragraph>
        <Select
          style={{ width: "100%" }}
          loading={candLoading}
          placeholder="选择待核销应收"
          value={allocAccountId}
          onChange={setAllocAccountId}
          notFoundContent={candLoading ? "加载中…" : "无同币种未结清应收"}
          options={candidates.map((c) => ({
            value: c.id,
            label: `${c.outbound_order_no} · 余额 ${formatMoney(c.balance)} ${c.currency}`,
          }))}
        />
      </Modal>

      {/* 作废纠错:零活动核销才可作废(有核销先反核销)。讲业务后果。 */}
      <Modal
        title="作废收款单"
        open={voidOpen}
        okText="确认作废"
        okButtonProps={{ danger: true }}
        confirmLoading={acting}
        onCancel={() => setVoidOpen(false)}
        onOk={doVoid}
      >
        <Typography.Paragraph type="secondary">
          作废后该收款单不再参与核销、不可恢复。若已有核销记录,请先逐条反核销。
        </Typography.Paragraph>
        <Input.TextArea
          rows={3}
          placeholder="作废原因(选填)"
          maxLength={500}
          value={voidReason}
          onChange={(e) => setVoidReason(e.target.value)}
        />
      </Modal>

      {/* 反核销:二次确认 + 原因;金额退回未分配、应收余额恢复。 */}
      <Modal
        title="反核销"
        open={reverseAllocId != null}
        okText="确认反核销"
        okButtonProps={{ danger: true }}
        confirmLoading={acting}
        onCancel={() => setReverseAllocId(null)}
        onOk={doReverse}
      >
        <Typography.Paragraph type="secondary">
          反核销后该笔金额退回收款单「未分配」,对应应收余额恢复。此操作会留痕。
        </Typography.Paragraph>
        <Input.TextArea
          rows={3}
          placeholder="反核销原因(选填)"
          maxLength={500}
          value={reverseReason}
          onChange={(e) => setReverseReason(e.target.value)}
        />
      </Modal>
    </Card>
  );
}
