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
  Modal,
  Space,
  Table,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { ArrowLeftOutlined } from "@ant-design/icons";
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
import { reverseRequestApi } from "@/lib/reverseRequest";

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
  const [reverseOpen, setReverseOpen] = useState(false);
  const [reverseReason, setReverseReason] = useState("");
  const [reverseBlocked, setReverseBlocked] = useState<OperationBlockedItem[] | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      setDetail(await inboundOrderApi.get(id));
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
          <Space>
            <Can perm={Permissions.INBOUND_MANAGE}>
              {inboundOrderReceivable(order.status) && (
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
              )}
              {inboundOrderUnreceivable(order.status) && (
                <Button
                  loading={busy}
                  onClick={() => {
                    setUnreceiveBlocked(null);
                    setUnreceiveOpen(true);
                  }}
                >
                  撤销入库
                </Button>
              )}
            </Can>
            <Can perm={Permissions.REVERSE_MANAGE}>
              {(order.status === "IN_TRANSIT" || order.status === "RECEIVED") && (
                <Button
                  loading={busy}
                  onClick={() => {
                    setReverseBlocked(null);
                    setReverseOpen(true);
                  }}
                >
                  发起取消申请
                </Button>
              )}
            </Can>
          </Space>
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
            <Descriptions.Item label="已核销">{formatAmount(payable.amount_allocated)}</Descriptions.Item>
            <Descriptions.Item label="余额">
              <span style={{ fontWeight: 600 }}>{formatAmount(payable.balance)}</span>
            </Descriptions.Item>
            <Descriptions.Item label="到期日">{payable.due_at || "—"}</Descriptions.Item>
            <Descriptions.Item label="生成时间">
              {formatDateTime(payable.created_at)}
            </Descriptions.Item>
          </Descriptions>
        </Card>
      )}

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

      <Modal
        title="发起履约中取消申请"
        open={reverseOpen}
        okText="提交申请"
        confirmLoading={busy}
        okButtonProps={{ disabled: !reverseReason.trim() }}
        onCancel={() => setReverseOpen(false)}
        onOk={async () => {
          setBusy(true);
          try {
            const created = await reverseRequestApi.create({
              inbound_order_id: id,
              reason: reverseReason.trim(),
            });
            message.success("已提交逆向申请");
            setReverseOpen(false);
            setReverseReason("");
            router.push(`/reverse-requests/${created.request.id}`);
          } catch (e) {
            if (e instanceof ApiError && e.code === 42303) {
              const docs = Array.isArray((e.data as { blocking_documents?: unknown })?.blocking_documents)
                ? ((e.data as { blocking_documents: Record<string, unknown>[] }).blocking_documents)
                : [];
              setReverseBlocked(
                docs.map((doc, i) => ({
                  key: `${String(doc.type || "doc")}-${String(doc.id || i)}`,
                  label: "出库单",
                  title: String(doc.no || doc.id || "活动出库单"),
                  detail: String(doc.status || ""),
                  onAction: doc.id ? () => router.push(`/outbound/${String(doc.id)}`) : undefined,
                })),
              );
            } else {
              message.error(resolveBizError(e, "提交失败"));
            }
          } finally {
            setBusy(false);
          }
        }}
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <span>提交后进入待审核;原入库单、采购单和应付账款不会被自动回滚。</span>
          {reverseBlocked ? (
            <OperationBlockedNotice
              title="无法发起:已存在活动出库单"
              nextAction="这张入库单所属销售链路已进入出库阶段,请走出库后售后逆向流程。"
              items={reverseBlocked}
            />
          ) : null}
          <Input.TextArea
            rows={3}
            placeholder="取消原因"
            value={reverseReason}
            onChange={(e) => {
              setReverseBlocked(null);
              setReverseReason(e.target.value);
            }}
          />
        </Space>
      </Modal>
    </Space>
  );
}
