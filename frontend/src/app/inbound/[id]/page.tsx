"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  App,
  Button,
  Card,
  DatePicker,
  Descriptions,
  Input,
  InputNumber,
  Modal,
  Radio,
  Space,
  Table,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  ArrowLeftOutlined,
  CheckOutlined,
  DollarOutlined,
  RollbackOutlined,
  StopOutlined,
  TruckOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import { Can } from "@/components/common/Can";
import { StatusTag } from "@/components/common/StatusTag";
import { PageLoading } from "@/components/common/PageLoading";
import { ListErrorState } from "@/components/common/ListErrorState";
import { OperationBlockedNotice, type OperationBlockedItem } from "@/components/common/OperationBlockedNotice";
import { Permissions } from "@/config/permission-matrix";
import { formatDateTime, formatQty } from "@/lib/format";
import { ApiError } from "@/lib/api";
import { resolveBizError } from "@/lib/errorMessages";
import {
  inboundOrderApi,
  type InboundOrderDetail,
  type InboundOrderLineOut,
} from "@/lib/inboundOrder";
import {
  INBOUND_ORDER_STATUS_META,
  inboundOrderReceivable,
  inboundOrderUnreceivable,
} from "@/lib/inboundOrderStatus";
import { PAYABLE_STATUS_META, formatAmount } from "@/lib/payable";
import { PurchaseReturnDrawer } from "@/components/inbound/PurchaseReturnDrawer";
import {
  AP_CREDIT_MEMO_STATUS_META,
  PURCHASE_RETURN_STATUS_META,
  purchaseReturnApi,
  type PurchaseReturnListItem,
} from "@/lib/purchaseReturn";
import {
  INVENTORY_DISPOSITION_STATUS_META,
  INVENTORY_DISPOSITION_RECEIPT_HANDLING_META,
  inventoryDispositionApi,
  type InventoryDispositionDetail,
  type InventoryDispositionReceiptHandling,
} from "@/lib/inventoryDisposition";
import {
  CUSTOMER_CREDIT_MEMO_STATUS_META,
  customerCreditMemoApi,
} from "@/lib/customerCreditMemo";

/** 41710 穿仓明细行。后端 data 形状:{ items: [{ sales_order_no, name_snapshot, available_qty }] }(镜像 41902)。 */
interface UnreceiveNegative {
  label: string;
  salesOrderNo?: string;
  available?: number | string;
}

function parseUnreceiveNegatives(data: unknown): UnreceiveNegative[] {
  const arr = Array.isArray((data as { items?: unknown })?.items)
    ? (data as { items: unknown[] }).items
    : [];
  return (arr as Record<string, unknown>[]).map((s) => ({
    label: String(s.name_snapshot || s.sku_id || "该 SKU"),
    salesOrderNo: (s.sales_order_no as string) || undefined,
    available: s.available_qty as number | string | undefined,
  }));
}

export default function InboundOrderDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { message } = App.useApp();
  const id = Number(params.id);

  const [detail, setDetail] = useState<InboundOrderDetail | null>(null);
  const [purchaseReturns, setPurchaseReturns] = useState<PurchaseReturnListItem[]>([]);
  const [inventoryDisposition, setInventoryDisposition] = useState<InventoryDispositionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState(false);
  // 确认入库对话框:到货日默认今天。
  const [receiveOpen, setReceiveOpen] = useState(false);
  const [arrivedAt, setArrivedAt] = useState(dayjs());
  // 撤销入库对话框:留痕原因(可空)。
  const [unreceiveOpen, setUnreceiveOpen] = useState(false);
  const [voidReason, setVoidReason] = useState("");
  const [unreceiveBlocked, setUnreceiveBlocked] = useState<OperationBlockedItem[] | null>(null);
  const [purchaseReturnOpen, setPurchaseReturnOpen] = useState(false);
  const [inTransitCancelOpen, setInTransitCancelOpen] = useState(false);
  const [inTransitCancelReason, setInTransitCancelReason] = useState("");
  const [dispositionOpen, setDispositionOpen] = useState(false);
  const [dispositionReason, setDispositionReason] = useState("");
  const [dispositionReceiptHandling, setDispositionReceiptHandling] =
    useState<InventoryDispositionReceiptHandling>("RECEIVE_TO_DISPOSITION");
  const [customerCreditOpen, setCustomerCreditOpen] = useState(false);
  const [customerCreditAmount, setCustomerCreditAmount] = useState<number | null>(null);
  const [customerCreditBasis, setCustomerCreditBasis] = useState("");
  const [customerCreditReason, setCustomerCreditReason] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const [nextDetail, returns, disposition] = await Promise.all([
        inboundOrderApi.get(id),
        purchaseReturnApi.list({ inbound_order_id: id, page: 1, size: 20 }),
        inventoryDispositionApi.byInbound(id),
      ]);
      setDetail(nextDetail);
      setPurchaseReturns(returns.items);
      setInventoryDisposition(disposition);
    } catch (e) {
      setLoadError(true);
      message.error(resolveBizError(e, "加载失败"));
    } finally {
      setLoading(false);
    }
  }, [id, message]);

  useEffect(() => {
    load();
  }, [load]);

  // 对话框动作:成功才关闭(内部吞异常,故用返回布尔判定)。
  async function actDialog(fn: () => Promise<unknown>, ok: string): Promise<boolean> {
    setBusy(true);
    try {
      await fn();
      message.success(ok);
      load();
      return true;
    } catch (e) {
      message.error(resolveBizError(e, "操作失败"));
      return false;
    } finally {
      setBusy(false);
    }
  }

  // 入库单据零成本列(契约 D3):明细无任何价格 / 行额列。
  const columns: ColumnsType<InboundOrderLineOut> = useMemo(
    () => [
      { title: "#", render: (_, __, i) => i + 1, width: 44 },
      { title: "商品", dataIndex: "name_snapshot", ellipsis: true },
      { title: "规格", dataIndex: "spec_text_snapshot", ellipsis: true, render: (v) => v || "—" },
      { title: "单位", dataIndex: "unit_snapshot", width: 70 },
      { title: "入库数量", dataIndex: "qty", width: 100, align: "right", render: formatQty },
      { title: "备注", dataIndex: "remark", ellipsis: true, render: (v) => v || "—" },
    ],
    [],
  );

  const currentInboundStatus = detail?.order.status;
  const purchaseReturnKindMeta = {
    PURCHASE_RETURN: { label: "采购退货", color: "info" },
    IN_TRANSIT_CANCELLATION: { label: "在途取消", color: "warning" },
  } as const;
  const purchaseReturnColumns: ColumnsType<PurchaseReturnListItem> = [
      { title: "退货单号", dataIndex: "no", width: 150 },
      {
        title: "类型",
        dataIndex: "return_kind",
        width: 110,
        render: (kind: PurchaseReturnListItem["return_kind"]) => (
          <StatusTag meta={purchaseReturnKindMeta} value={kind} />
        ),
      },
      {
        title: "状态",
        dataIndex: "status",
        width: 130,
        render: (s: PurchaseReturnListItem["status"]) => (
          <StatusTag meta={PURCHASE_RETURN_STATUS_META} value={s} />
        ),
      },
      {
        title: "供应商贷项单",
        dataIndex: "ap_credit_memo_status",
        width: 150,
        render: (s: PurchaseReturnListItem["ap_credit_memo_status"]) =>
          s ? <StatusTag meta={AP_CREDIT_MEMO_STATUS_META} value={s} /> : "—",
      },
      { title: "行数", dataIndex: "line_count", width: 80, align: "right" },
      {
        title: "数量",
        dataIndex: "total_qty",
        width: 100,
        align: "right",
        render: formatQty,
      },
      {
        title: "金额",
        dataIndex: "total_amount",
        width: 120,
        align: "right",
        render: (v: number | string | null) => (v == null ? "—" : formatAmount(v)),
      },
      {
        title: "操作",
        key: "actions",
        width: 220,
        render: (_, row) => (
          <Space>
            {row.status === "PENDING_APPROVAL" && (
              <Can perm={Permissions.PURCHASE_MANAGE}>
                <Button
                  size="small"
                  icon={<CheckOutlined />}
                  loading={busy}
                  onClick={() =>
                    actDialog(
                      () => purchaseReturnApi.approve(row.id),
                      "已审核通过采购退货单",
                    )
                  }
                >
                  审核通过
                </Button>
              </Can>
            )}
            {row.status === "APPROVED" && (
              <Can perm={Permissions.INBOUND_MANAGE}>
                <Button
                  size="small"
                  icon={
                    row.return_kind === "IN_TRANSIT_CANCELLATION"
                      ? <StopOutlined />
                      : <TruckOutlined />
                  }
                  loading={busy}
                  onClick={() =>
                    actDialog(
                      () => row.return_kind === "IN_TRANSIT_CANCELLATION"
                        ? purchaseReturnApi.confirmInTransitCancellation(row.id, {})
                        : purchaseReturnApi.confirmReturnShipment(row.id, {}),
                      row.return_kind === "IN_TRANSIT_CANCELLATION"
                        ? "已确认在途取消"
                        : "已确认退货出库",
                    )
                  }
                >
                  {row.return_kind === "IN_TRANSIT_CANCELLATION"
                    ? "确认在途取消"
                    : "确认退货出库"}
                </Button>
              </Can>
            )}
          </Space>
        ),
      },
  ];

  if (loadError && !detail) return <ListErrorState onRetry={load} />;
  if (loading || !detail) return <PageLoading />;

  const { order, lines, payable } = detail;

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      <Card
        title={
          <Space size={8}>
            <Button
              type="text"
              size="small"
              icon={<ArrowLeftOutlined />}
              onClick={() => router.push("/inbound")}
              aria-label="返回列表"
            />
            <span>{order.no}</span>
            <StatusTag meta={INBOUND_ORDER_STATUS_META} value={order.status} />
          </Space>
        }
        extra={
          <Can perm={Permissions.INBOUND_MANAGE}>
            <Space>
              {inboundOrderReceivable(order.status) && (
                <>
                  <Can perm={Permissions.PURCHASE_MANAGE}>
                    <Button
                      danger
                      icon={<StopOutlined />}
                      loading={busy}
                      onClick={() => {
                        setInTransitCancelReason("");
                        setInTransitCancelOpen(true);
                      }}
                    >
                      在途取消
                    </Button>
                    <Button
                      danger
                      icon={<DollarOutlined />}
                      loading={busy}
                      onClick={() => {
                        setDispositionReason("");
                        setDispositionReceiptHandling("RECEIVE_TO_DISPOSITION");
                        setDispositionOpen(true);
                      }}
                    >
                      库存处置
                    </Button>
                  </Can>
                  <Button
                    type="primary"
                    loading={busy}
                    onClick={() => {
                      // 默认取预计到货日(运营自己填的到货估计,少改一次);未填才退回今天。
                      setArrivedAt(order.eta ? dayjs(order.eta) : dayjs());
                      setReceiveOpen(true);
                    }}
                  >
                    确认入库
                  </Button>
                </>
              )}
              {inboundOrderUnreceivable(order.status) && (
                <>
                  <Can perm={Permissions.PURCHASE_MANAGE}>
                    <Button icon={<RollbackOutlined />} onClick={() => setPurchaseReturnOpen(true)}>
                      采购退货
                    </Button>
                    <Button
                      danger
                      icon={<DollarOutlined />}
                      onClick={() => {
                        setDispositionReason("");
                        setDispositionReceiptHandling("RECEIVE_TO_DISPOSITION");
                        setDispositionOpen(true);
                      }}
                    >
                      库存处置
                    </Button>
                  </Can>
                  <Button
                    loading={busy}
                    onClick={() => {
                      setUnreceiveBlocked(null);
                      setUnreceiveOpen(true);
                    }}
                  >
                    撤销入库
                  </Button>
                </>
              )}
            </Space>
          </Can>
        }
      >
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="采购单号">
            {/* 无 purchase:read → 降级纯文本(如仓库入库角色)。DESIGN §7 单据链接降级。 */}
            <Can
              perm={Permissions.PURCHASE_READ}
              fallback={<span>{order.purchase_order_no}</span>}
            >
              <Button
                type="link"
                size="small"
                style={{ padding: 0 }}
                onClick={() => router.push(`/purchasing/orders/${order.purchase_order_id}`)}
              >
                {order.purchase_order_no}
              </Button>
            </Can>
          </Descriptions.Item>
          <Descriptions.Item label="供应商">{order.supplier_display}</Descriptions.Item>
          <Descriptions.Item label="状态">
            <StatusTag meta={INBOUND_ORDER_STATUS_META} value={order.status} />
          </Descriptions.Item>
          <Descriptions.Item label="实际到货">{order.arrived_at || "—"}</Descriptions.Item>
          <Descriptions.Item label="备注" span={2}>
            {order.remark || "—"}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="头程物流" size="small">
        <Descriptions column={2} size="small">
          <Descriptions.Item label="承运商">{order.carrier_name || "—"}</Descriptions.Item>
          <Descriptions.Item label="头程单号">{order.tracking_no || "—"}</Descriptions.Item>
          <Descriptions.Item label="发货日期">{order.shipped_at || "—"}</Descriptions.Item>
          <Descriptions.Item label="预计到货">{order.eta || "—"}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="入库明细">
        <Table<InboundOrderLineOut>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={lines}
          pagination={false}
          scroll={{ x: 720 }}
        />
      </Card>

      {/* payable 卡:仅当响应含 payable 键时渲染(整块红线门控,前端不自判权限)。 */}
      {payable && (
        <Card
          title="应付账款"
          size="small"
          extra={<StatusTag meta={PAYABLE_STATUS_META} value={payable.status} />}
        >
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="币种">{payable.currency}</Descriptions.Item>
            <Descriptions.Item label="应付金额">
              <span style={{ fontWeight: 600 }}>
                {payable.currency} {formatAmount(payable.amount_original)}
              </span>
            </Descriptions.Item>
            <Descriptions.Item label="已贷记">{formatAmount(payable.amount_credited)}</Descriptions.Item>
            <Descriptions.Item label="已核销">{formatAmount(payable.amount_allocated)}</Descriptions.Item>
            <Descriptions.Item label="未结应付">
              <span style={{ fontWeight: 600 }}>{formatAmount(payable.amount_outstanding)}</span>
            </Descriptions.Item>
            <Descriptions.Item label="到期日">{payable.due_at || "—"}</Descriptions.Item>
            <Descriptions.Item label="生成时间">
              {formatDateTime(payable.created_at)}
            </Descriptions.Item>
          </Descriptions>
        </Card>
      )}

      {inventoryDisposition && (
        <Card
          title="库存处置"
          size="small"
          extra={
            <Space>
              {!inventoryDisposition.customer_credit_memo
                && ["HELD", "CLOSED_WITHOUT_RECEIPT"].includes(inventoryDisposition.order.status) ? (
                <Can perm={Permissions.CUSTOMER_CREDIT_CREATE}>
                  <Button
                    size="small"
                    icon={<DollarOutlined />}
                    onClick={() => {
                      setCustomerCreditAmount(null);
                      setCustomerCreditBasis(inventoryDisposition.order.reason || "");
                      setCustomerCreditReason(inventoryDisposition.order.reason || "");
                      setCustomerCreditOpen(true);
                    }}
                  >
                    客户余额贷项
                  </Button>
                </Can>
              ) : null}
              <StatusTag
                meta={INVENTORY_DISPOSITION_STATUS_META}
                value={inventoryDisposition.order.status}
              />
            </Space>
          }
        >
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="处置单号">{inventoryDisposition.order.no}</Descriptions.Item>
            <Descriptions.Item label="收货处理">
              {INVENTORY_DISPOSITION_RECEIPT_HANDLING_META[
                inventoryDisposition.order.receipt_handling
              ]}
            </Descriptions.Item>
            <Descriptions.Item label="采购币种">
              {inventoryDisposition.order.purchase_currency}
            </Descriptions.Item>
            <Descriptions.Item label="应付成本参考">
              {inventoryDisposition.order.supplier_payable_amount == null
                ? "—"
                : formatAmount(inventoryDisposition.order.supplier_payable_amount)}
            </Descriptions.Item>
            <Descriptions.Item label="原因" span={2}>
              {inventoryDisposition.order.reason || "—"}
            </Descriptions.Item>
            <Descriptions.Item label="客户余额贷项单">
              {inventoryDisposition.customer_credit_memo ? (
                <Space size={6}>
                  <span>{inventoryDisposition.customer_credit_memo.no}</span>
                  <StatusTag
                    meta={CUSTOMER_CREDIT_MEMO_STATUS_META}
                    value={inventoryDisposition.customer_credit_memo.status}
                  />
                </Space>
              ) : "—"}
            </Descriptions.Item>
            <Descriptions.Item label="客户贷方金额">
              {inventoryDisposition.customer_credit_memo
                ? `${formatAmount(inventoryDisposition.customer_credit_memo.amount)} CNY`
                : "—"}
            </Descriptions.Item>
          </Descriptions>
        </Card>
      )}

      <Card title="相关采购退货单" size="small">
        <Table<PurchaseReturnListItem>
          rowKey="id"
          size="small"
          columns={purchaseReturnColumns}
          dataSource={purchaseReturns}
          pagination={false}
          locale={{ emptyText: "暂无采购退货单" }}
          scroll={{ x: 920 }}
        />
      </Card>

      {/* 确认入库:只确认库存事实,应付已在创建入库单时生成。 */}
      <Modal
        title="确认入库"
        open={receiveOpen}
        okText="确认入库"
        confirmLoading={busy}
        onCancel={() => setReceiveOpen(false)}
        onOk={async () => {
          const ok = await actDialog(
            () => inboundOrderApi.receive(id, arrivedAt.format("YYYY-MM-DD")),
            "已确认入库",
          );
          if (ok) setReceiveOpen(false);
        }}
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <span>确认后将形成销售单维度库存;供应商应付已在创建入库单时生成。</span>
          <div>
            <div style={{ marginBottom: 4 }}>实际到货日</div>
            <DatePicker
              style={{ width: "100%" }}
              value={arrivedAt}
              allowClear={false}
              onChange={(d) => d && setArrivedAt(d)}
            />
          </div>
        </Space>
      </Modal>

      {/* 在途取消:货未确认入库,不扣库存;提交后走采购审核与供应商贷项单。 */}
      <Modal
        title="在途取消"
        open={inTransitCancelOpen}
        okText="提交审核"
        okButtonProps={{ danger: true }}
        confirmLoading={busy}
        onCancel={() => setInTransitCancelOpen(false)}
        onOk={async () => {
          const ok = await actDialog(
            () => purchaseReturnApi.createInTransitCancellation({
              inbound_order_id: id,
              reason: inTransitCancelReason.trim() || null,
            }),
            "已提交在途取消单",
          );
          if (ok) {
            setInTransitCancelOpen(false);
            setInTransitCancelReason("");
          }
        }}
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <span>提交后不会扣减库存;审核通过并确认在途取消后,系统会关闭该入库单并生成供应商贷项单。</span>
          <Input.TextArea
            rows={3}
            placeholder="取消原因(选填,用于采购退货单和供应商贷项单)"
            value={inTransitCancelReason}
            onChange={(e) => setInTransitCancelReason(e.target.value)}
          />
        </Space>
      </Modal>

      {/* 库存处置:供应商侧应付保持,客户退款/损失确认由真实财务单据承载。 */}
      <Modal
        title="库存处置"
        open={dispositionOpen}
        okText="创建处置单"
        okButtonProps={{ danger: true }}
        confirmLoading={busy}
        onCancel={() => setDispositionOpen(false)}
        onOk={async () => {
          const ok = await actDialog(
            () => inventoryDispositionApi.create({
              inbound_order_id: id,
              receipt_handling: order.status === "IN_TRANSIT"
                ? dispositionReceiptHandling
                : "RECEIVE_TO_DISPOSITION",
              reason: dispositionReason.trim() || null,
            }),
            "已创建库存处置单",
          );
          if (ok) {
            setDispositionOpen(false);
            setDispositionReason("");
            setDispositionReceiptHandling("RECEIVE_TO_DISPOSITION");
          }
        }}
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <span>供应商应付不会冲正;客户退款、损失确认需由后续财务流程单独处理。</span>
          {order.status === "IN_TRANSIT" ? (
            <div>
              <div style={{ marginBottom: 4 }}>收货处理</div>
              <Radio.Group
                value={dispositionReceiptHandling}
                onChange={(e) =>
                  setDispositionReceiptHandling(e.target.value as InventoryDispositionReceiptHandling)
                }
              >
                <Space orientation="vertical">
                  <Radio value="RECEIVE_TO_DISPOSITION">
                    到货代仓收货,直接进入待处置
                  </Radio>
                  <Radio value="CLOSE_WITHOUT_RECEIPT">
                    终止入仓,关闭未收货
                  </Radio>
                </Space>
              </Radio.Group>
            </div>
          ) : null}
          <Input.TextArea
            rows={3}
            placeholder="处置原因(选填,用于库存处置单)"
            value={dispositionReason}
            onChange={(e) => setDispositionReason(e.target.value)}
          />
        </Space>
      </Modal>

      <Modal
        title="客户余额贷项单"
        open={customerCreditOpen}
        okText="提交财务审核"
        confirmLoading={busy}
        okButtonProps={{
          disabled: !customerCreditAmount || customerCreditAmount <= 0 || !customerCreditBasis.trim(),
        }}
        onCancel={() => setCustomerCreditOpen(false)}
        onOk={async () => {
          if (!inventoryDisposition || !customerCreditAmount || !customerCreditBasis.trim()) return;
          const ok = await actDialog(
            () => customerCreditMemoApi.create({
              inventory_disposition_order_id: inventoryDisposition.order.id,
              amount: customerCreditAmount.toFixed(2),
              currency: "CNY",
              amount_basis: customerCreditBasis.trim(),
              reason: customerCreditReason.trim() || null,
            }),
            "已提交客户余额贷项单",
          );
          if (ok) {
            setCustomerCreditOpen(false);
            setCustomerCreditAmount(null);
            setCustomerCreditBasis("");
            setCustomerCreditReason("");
          }
        }}
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <span>金额固定进入客户人民币余额;提交后仍需财务过账,不会冲减供应商应付。</span>
          <div>
            <div style={{ marginBottom: 4 }}>贷项金额 CNY</div>
            <InputNumber
              min={0.01}
              precision={2}
              style={{ width: "100%" }}
              value={customerCreditAmount}
              onChange={(v) => setCustomerCreditAmount(typeof v === "number" ? v : null)}
            />
          </div>
          <Input.TextArea
            rows={3}
            placeholder="人民币金额依据(必填,如线下审批单号/赔付计算说明)"
            value={customerCreditBasis}
            maxLength={1000}
            showCount
            onChange={(e) => setCustomerCreditBasis(e.target.value)}
          />
          <Input.TextArea
            rows={3}
            placeholder="原因(选填,用于财务审核)"
            value={customerCreditReason}
            onChange={(e) => setCustomerCreditReason(e.target.value)}
          />
        </Space>
      </Modal>

      {/* 撤销入库:二次确认 + 留痕原因。 */}
      <Modal
        title="撤销入库"
        open={unreceiveOpen}
        okText="确认撤销"
        okButtonProps={{ danger: true }}
        confirmLoading={busy}
        onCancel={() => setUnreceiveOpen(false)}
        onOk={async () => {
          setBusy(true);
          try {
            await inboundOrderApi.unreceive(id, voidReason.trim() || null);
            message.success("已撤销入库");
            setUnreceiveOpen(false);
            setVoidReason("");
            load();
          } catch (e) {
            // 41710 穿仓:按 (SO,SKU) 明细展示;已出库后原链路不可通过撤销出库释放库存。
            if (e instanceof ApiError && e.code === 41710) {
              const rows = parseUnreceiveNegatives(e.data);
              setUnreceiveBlocked(
                rows.map((s, i) => ({
                  key: `${s.salesOrderNo ?? "so"}-${s.label}-${i}`,
                  label: "库存明细",
                  title: s.label,
                  detail: [
                    s.salesOrderNo ? `销售单 ${s.salesOrderNo}` : null,
                    s.available !== undefined ? `撤回后可发 ${formatQty(s.available)}` : null,
                  ]
                    .filter(Boolean)
                    .join(" · "),
                })),
              );
            } else {
              message.error(resolveBizError(e, "操作失败"));
            }
          } finally {
            setBusy(false);
          }
        }}
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <span>撤销后回到在途态,只撤销库存事实;供应商应付保持不变。</span>
          {unreceiveBlocked ? (
            <OperationBlockedNotice
              title="无法撤销:库存已被出库消费"
              nextAction="已确认出库的库存不可回退原流程;当前系统暂不支持出库后线上冲正,请联系管理员处理。"
              fallbackText="部分货物已被出库消费,不可撤销入库。"
              items={unreceiveBlocked}
            />
          ) : null}
          <Input.TextArea
            rows={2}
            placeholder="撤销原因(选填,留痕)"
            value={voidReason}
            onChange={(e) => {
              setUnreceiveBlocked(null);
              setVoidReason(e.target.value);
            }}
          />
        </Space>
      </Modal>

      <PurchaseReturnDrawer
        open={purchaseReturnOpen}
        inboundOrderId={order.id}
        inboundOrderNo={order.no}
        onClose={() => setPurchaseReturnOpen(false)}
        onSaved={() => {
          setPurchaseReturnOpen(false);
          load();
        }}
      />
    </Space>
  );
}
