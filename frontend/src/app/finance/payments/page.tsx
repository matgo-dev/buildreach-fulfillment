"use client";
// 🔴 整域红线:整页由 layout 的 RouteGuard(payment:read)门控 —— 无权不渲染/不请求,
// 后端亦整端点 403。付款关联供应商 + 采购付款金额,前端不下发给无权角色。
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  App,
  Button,
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
import { ListTable } from "@/components/common/ListTable";
import { ListErrorState } from "@/components/common/ListErrorState";
import { ListPageCard, ListPageBody } from "@/components/common/ListPageCard";
import { selectFilter } from "@/components/common/SelectFilter";
import { useListQuery } from "@/hooks/useListQuery";
import { Permissions } from "@/config/permission-matrix";
import { supplierApi, type SupplierListItem } from "@/lib/supplier";
import { formatDateTime, formatMoney } from "@/lib/format";
import { resolveBizError } from "@/lib/errorMessages";
import {
  PAYMENT_STATUS_META,
  paymentApi,
  type PaymentDetail,
  type PaymentListItem,
  type PaymentStatusFilter,
} from "@/lib/payment";
import { payableApi, type PayableListItem } from "@/lib/payable";
import { CURRENCIES } from "@/lib/currencies";

// 状态 tabs:全部 + 三派生态 + 作废(无待认领)。
const STATUS_TABS = [
  { label: "全部", value: "" },
  ...Object.entries(PAYMENT_STATUS_META).map(([v, m]) => ({ label: m.label, value: v })),
  { label: "已作废", value: "VOIDED" },
];

function PaymentStatusTag({ status, voidedAt }: { status: string; voidedAt: string | null }) {
  if (voidedAt) return <Tag>已作废</Tag>;
  return <StatusTag meta={PAYMENT_STATUS_META} value={status} />;
}

export default function PaymentListPage() {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  // D10 一键入口:从应付抽屉带 supplier_id 预筛进来(useSearchParams,与 /purchasing/orders 同式)。
  const presetSupplierId = useSearchParams().get("supplier_id");

  const [status, setStatus] = useState("");
  const [keyword, setKeyword] = useState("");
  const [supplierId, setSupplierId] = useState<number | undefined>(
    presetSupplierId ? Number(presetSupplierId) : undefined,
  );
  const [currency, setCurrency] = useState<string | undefined>(undefined);
  const [suppliers, setSuppliers] = useState<SupplierListItem[]>([]);

  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);

  const [detail, setDetail] = useState<PaymentDetail | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [acting, setActing] = useState(false);

  const [allocOpen, setAllocOpen] = useState(false);
  const [allocAccountId, setAllocAccountId] = useState<number | undefined>(undefined);
  const [candidates, setCandidates] = useState<PayableListItem[]>([]);
  const [candLoading, setCandLoading] = useState(false);

  const [voidOpen, setVoidOpen] = useState(false);
  const [voidReason, setVoidReason] = useState("");

  const [reverseAllocId, setReverseAllocId] = useState<number | null>(null);
  const [reverseReason, setReverseReason] = useState("");

  const fetcher = useCallback(
    ({ page, size }: { page: number; size: number }) =>
      paymentApi.list({
        supplier_id: supplierId,
        currency: currency || undefined,
        status: (status || undefined) as PaymentStatusFilter | undefined,
        q: keyword.trim() || undefined,
        page,
        size,
      }),
    [supplierId, currency, status, keyword],
  );
  const { rows, setPage, loading, loadError, load, pagination } = useListQuery<PaymentListItem>(
    fetcher,
    { errorMessage: "加载付款单列表失败" },
  );

  // 供应商下拉(筛选 + 登记共用)。
  useEffect(() => {
    supplierApi
      .list({ size: 100 })
      .then((res) => setSuppliers(res.items))
      .catch(() => undefined);
  }, []);

  async function openDetail(id: number) {
    setDetailOpen(true);
    setDetailLoading(true);
    setDetail(null);
    try {
      setDetail(await paymentApi.get(id));
    } catch (e) {
      message.error(resolveBizError(e, "加载付款单详情失败"));
      setDetailOpen(false);
    } finally {
      setDetailLoading(false);
    }
  }

  function applyDetail(d: PaymentDetail) {
    setDetail(d);
    load();
  }

  async function onCreate() {
    const v = await form.validateFields().catch(() => null);
    if (!v) return;
    setCreating(true);
    try {
      const d = await paymentApi.create({
        amount: String(v.amount),
        currency: v.currency,
        paid_at: (v.paid_at as dayjs.Dayjs).format("YYYY-MM-DD"),
        supplier_id: v.supplier_id,
        account_info: v.account_info?.trim() || null,
        note: v.note?.trim() || null,
      });
      message.success(`已登记付款 ${d.payment.payment_no}`);
      setCreateOpen(false);
      form.resetFields();
      load();
      openDetail(d.payment.id);
    } catch (e) {
      message.error(resolveBizError(e, "登记失败"));
    } finally {
      setCreating(false);
    }
  }

  async function openAllocate() {
    if (!detail) return;
    setAllocOpen(true);
    setAllocAccountId(undefined);
    setCandLoading(true);
    try {
      const res = await payableApi.list({ supplier_id: detail.payment.supplier_id, size: 100 });
      setCandidates(
        res.items.filter(
          (p) => p.status !== "PAID" && p.currency === detail.payment.currency,
        ),
      );
    } catch (e) {
      message.error(resolveBizError(e, "加载待核销应付失败"));
    } finally {
      setCandLoading(false);
    }
  }

  async function doAllocate() {
    if (!detail || !allocAccountId) return;
    setActing(true);
    try {
      applyDetail(await paymentApi.allocate(detail.payment.id, allocAccountId));
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
      applyDetail(await paymentApi.void(detail.payment.id, voidReason.trim() || null));
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
      applyDetail(await paymentApi.reverseAllocation(reverseAllocId, reverseReason.trim() || null));
      message.success("已反核销");
      setReverseAllocId(null);
      setReverseReason("");
    } catch (e) {
      message.error(resolveBizError(e, "反核销失败"));
    } finally {
      setActing(false);
    }
  }

  const columns: ColumnsType<PaymentListItem> = [
    { title: "付款单号", dataIndex: "payment_no", width: 170 },
    { title: "供应商", dataIndex: "supplier_display", width: 180, ellipsis: true },
    {
      title: "币种",
      dataIndex: "currency",
      width: 90,
      ...selectFilter<PaymentListItem>(CURRENCIES.map((c) => ({ text: c, value: c }))),
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
      render: (_, r) => <PaymentStatusTag status={r.status} voidedAt={r.voided_at} />,
    },
    { title: "付款日", dataIndex: "paid_at", width: 120 },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 170,
      render: (v: string) => formatDateTime(v),
    },
  ];

  const p = detail?.payment;
  const canAllocate = p && !p.voided_at && p.amount_unallocated > 0;
  const canVoid = p && !p.voided_at;

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
            placeholder="付款单号 / 供应商名"
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
            placeholder="供应商"
            optionFilterProp="label"
            style={{ width: 220 }}
            value={supplierId}
            onChange={(v) => {
              setSupplierId(v);
              setPage(1);
            }}
            options={suppliers.map((s) => ({ value: s.id, label: `${s.code} · ${s.name}` }))}
          />
        </Space>
        <Can perm={Permissions.PAYMENT_MANAGE}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            登记付款
          </Button>
        </Can>
      </Space>

      <ListPageBody>
        {loadError && !rows.length ? (
          <ListErrorState onRetry={load} />
        ) : (
          <ListTable<PaymentListItem>
            rowKey="id"
            columns={columns}
            dataSource={rows}
            loading={loading}
            scroll={{ x: 1290 }}
            locale={{ emptyText: "暂无付款单" }}
            onChange={(_, filters) => {
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
      </ListPageBody>

      {/* 登记付款:amount/currency/paid_at/supplier 必填(无待认领态)。 */}
      {/* 登记付款:表单走抽屉(DESIGN §5/§11.7)。 */}
      <Drawer
        title="登记付款"
        open={createOpen}
        size="min(520px, 92vw)"
        destroyOnHidden
        onClose={() => {
          setCreateOpen(false);
          form.resetFields();
        }}
        footer={
          <Space style={{ width: "100%", justifyContent: "flex-end" }}>
            <Button
              onClick={() => {
                setCreateOpen(false);
                form.resetFields();
              }}
              disabled={creating}
            >
              取消
            </Button>
            <Button type="primary" loading={creating} onClick={onCreate}>
              登记
            </Button>
          </Space>
        }
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ currency: "USD", paid_at: dayjs() }}
        >
          <Form.Item
            name="supplier_id"
            label="供应商"
            rules={[{ required: true, message: "请选择供应商" }]}
          >
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="选择供应商"
              options={suppliers.map((s) => ({ value: s.id, label: `${s.code} · ${s.name}` }))}
            />
          </Form.Item>
          <Form.Item
            name="amount"
            label="付款金额"
            rules={[{ required: true, message: "请输入付款金额" }]}
          >
            {/* precision=2:两位小数与后端 Decimal(decimal_places=2)/DB Numeric(18,2) 对齐,禁三位小数被静默舍入。 */}
            <InputNumber min={0.01} step={0.01} precision={2} style={{ width: "100%" }} placeholder="登记即定死,> 0" />
          </Form.Item>
          <Form.Item name="currency" label="币种" rules={[{ required: true }]}>
            <Select options={CURRENCIES.map((c) => ({ value: c, label: c }))} />
          </Form.Item>
          <Form.Item name="paid_at" label="付款日" rules={[{ required: true }]}>
            <DatePicker style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="account_info" label="付款账户信息">
            <Input placeholder="选填,如银行流水摘要" maxLength={200} />
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input.TextArea rows={2} placeholder="选填" maxLength={500} />
          </Form.Item>
        </Form>
      </Drawer>

      {/* 详情抽屉:单头 + 未分配余额高亮 + 活动核销记录。 */}
      <Drawer
        title={p ? `付款单 ${p.payment_no}` : "付款单详情"}
        size={640}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        loading={detailLoading}
        extra={
          p && (
            <Can perm={Permissions.PAYMENT_MANAGE}>
              <Space>
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
        {p && (
          <>
            {p.voided_at && (
              <Tag color="error" style={{ marginBottom: 12 }}>
                已作废{p.void_reason ? ` · ${p.void_reason}` : ""}
              </Tag>
            )}
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="供应商">{p.supplier_display}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <PaymentStatusTag status={p.status} voidedAt={p.voided_at} />
              </Descriptions.Item>
              <Descriptions.Item label="币种">{p.currency}</Descriptions.Item>
              <Descriptions.Item label="付款日">{p.paid_at}</Descriptions.Item>
              <Descriptions.Item label="金额">
                {formatMoney(p.amount)} {p.currency}
              </Descriptions.Item>
              <Descriptions.Item label="已分配">
                {formatMoney(p.amount_allocated)} {p.currency}
              </Descriptions.Item>
              <Descriptions.Item label="未分配余额" span={2}>
                <Typography.Text strong type={p.amount_unallocated > 0 ? "success" : undefined}>
                  {formatMoney(p.amount_unallocated)} {p.currency}
                </Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label="付款账户" span={2}>
                {p.account_info || "—"}
              </Descriptions.Item>
              <Descriptions.Item label="备注" span={2}>
                {p.note || "—"}
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
                  render: (v: number) => formatMoney(v),
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
                    p.voided_at ? null : (
                      <Can perm={Permissions.PAYMENT_MANAGE}>
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

      {/* 人工核销:选一张未结清应付,金额由后端自动取满 min。 */}
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
          核销金额自动取「未分配余额」与「应付余额」的较小值,无需填写。
        </Typography.Paragraph>
        <Select
          style={{ width: "100%" }}
          loading={candLoading}
          placeholder="选择待核销应付"
          value={allocAccountId}
          onChange={setAllocAccountId}
          notFoundContent={candLoading ? "加载中…" : "无同币种未结清应付"}
          options={candidates.map((c) => ({
            value: c.id,
            label: `${c.inbound_order_no} · 余额 ${formatMoney(c.balance)} ${c.currency}`,
          }))}
        />
      </Modal>

      {/* 作废纠错:零活动核销才可作废(有核销先反核销)。 */}
      <Modal
        title="作废付款单"
        open={voidOpen}
        okText="确认作废"
        okButtonProps={{ danger: true }}
        confirmLoading={acting}
        onCancel={() => setVoidOpen(false)}
        onOk={doVoid}
      >
        <Typography.Paragraph type="secondary">
          作废后该付款单不再参与核销、不可恢复。若已有核销记录,请先逐条反核销。
        </Typography.Paragraph>
        <Input.TextArea
          rows={3}
          placeholder="作废原因(选填)"
          maxLength={500}
          value={voidReason}
          onChange={(e) => setVoidReason(e.target.value)}
        />
      </Modal>

      {/* 反核销:二次确认 + 原因;金额退回未分配、应付余额恢复。 */}
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
          反核销后该笔金额退回付款单「未分配」,对应应付余额恢复。此操作会留痕。
        </Typography.Paragraph>
        <Input.TextArea
          rows={3}
          placeholder="反核销原因(选填)"
          maxLength={500}
          value={reverseReason}
          onChange={(e) => setReverseReason(e.target.value)}
        />
      </Modal>
    </ListPageCard>
  );
}
