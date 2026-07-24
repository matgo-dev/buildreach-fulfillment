"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { App, Button, Card, Descriptions, Input, Modal, Space, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import { ArrowLeftOutlined, ShoppingCartOutlined } from "@ant-design/icons";
import { Can } from "@/components/common/Can";
import { StatusTag } from "@/components/common/StatusTag";
import { ProgressCell } from "@/components/common/ProgressCell";
import { PageLoading } from "@/components/common/PageLoading";
import { ListErrorState } from "@/components/common/ListErrorState";
import { Permissions } from "@/config/permission-matrix";
import { useAuthStore } from "@/stores/authStore";
import { formatDateTime, formatQty } from "@/lib/format";
import { resolveBizError } from "@/lib/errorMessages";
import {
  formatPrice,
  salesOrderApi,
  type SalesOrderLineOut,
  type SalesOrderOut,
} from "@/lib/salesOrder";
import { SALES_ORDER_STATUS_META, salesOrderCancellable } from "@/lib/salesOrderStatus";
import { colors } from "@/lib/tokens";
import { formatCost, type RelatedPurchaseOrder } from "@/lib/purchaseOrder";
import {
  PURCHASE_ORDER_STATUS_META,
  PURCHASE_PROGRESS_META,
} from "@/lib/purchaseOrderStatus";
import { PurchaseOrderBuilder } from "@/components/purchasing/PurchaseOrderBuilder";
import type { StockBalanceLine } from "@/lib/inventory";
import { NumCell } from "@/components/common/NumCell";
import type { RelatedOutboundOrder } from "@/lib/outboundOrder";
import { OUTBOUND_ORDER_STATUS_META } from "@/lib/outboundOrderStatus";

export default function SalesOrderDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { message } = App.useApp();
  const id = Number(params.id);
  // 🔴 红线可见性:无权者后端已脱敏为 null,渲染层再整列/整项藏掉(DESIGN.md §9)。
  const canSeePrice = useAuthStore((s) => s.hasPermission(Permissions.RECEIVABLE_READ));
  const canSeeCost = useAuthStore((s) => s.hasPermission(Permissions.PURCHASE_READ_COST));

  const [order, setOrder] = useState<SalesOrderOut | null>(null);
  const [lines, setLines] = useState<SalesOrderLineOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [purchasing, setPurchasing] = useState(false);
  // 取消对话框:留痕原因(可空)。危险操作只放详情页(同入库先例)。
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState("");
  const [cancelling, setCancelling] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const { order: o, lines: ls } = await salesOrderApi.get(id);
      setOrder(o);
      setLines(ls);
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

  const columns: ColumnsType<SalesOrderLineOut> = useMemo(
    () => [
      { title: "#", render: (_, __, i) => i + 1, width: 44 },
      { title: "商品", dataIndex: "name_snapshot", ellipsis: true },
      { title: "规格", dataIndex: "spec_text_snapshot", ellipsis: true, render: (v) => v || "—" },
      { title: "单位", dataIndex: "unit_snapshot", width: 70 },
      { title: "数量", dataIndex: "qty", width: 90, align: "right", render: formatQty },
      // 采购覆盖度(非红线,始终可见)。已采=covered_qty;剩余=qty−covered。
      {
        title: "已采",
        key: "covered",
        width: 80,
        align: "right",
        render: (_, r) => formatQty(r.covered_qty ?? 0),
      },
      {
        title: "剩余",
        key: "remaining",
        width: 80,
        align: "right",
        render: (_, r) => formatQty(Number(r.qty) - Number(r.covered_qty ?? 0)),
      },
      // 🔴 售价红线:无 receivable:read 者整两列不渲染(DESIGN.md §9);render 仍走 formatPrice 兜漂移。
      ...((canSeePrice
        ? [
            { title: "单价", dataIndex: "unit_price", width: 110, align: "right", render: formatPrice },
            { title: "金额", dataIndex: "line_total", width: 120, align: "right", render: formatPrice },
          ]
        : []) as ColumnsType<SalesOrderLineOut>),
      { title: "备注", dataIndex: "remark", ellipsis: true, render: (v) => v || "—" },
    ],
    [canSeePrice],
  );

  if (loadError && !order) return <ListErrorState onRetry={load} />;
  if (loading || !order) return <PageLoading />;

  const relatedPOs = order.related_purchase_orders; // undefined = 无 purchase:read,不渲染区块
  const stockBalances = order.stock_balances; // undefined = 无 inventory:read,不渲染区块(响应键存在与否驱动渲染)
  const relatedOutbounds = order.related_outbound_orders; // undefined = 无 outbound:read,不渲染区块

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card
        title={
          <Space size={8}>
            <Button
              type="text"
              size="small"
              icon={<ArrowLeftOutlined />}
              onClick={() => router.push("/sales/orders")}
              aria-label="返回列表"
            />
            <span>{order.no}</span>
            <StatusTag meta={SALES_ORDER_STATUS_META} value={order.status} />
            {/* CANCELLED 隐藏进度徽标:全 PO 已取消会回「未采购」,挂着误导(评审 S4)。 */}
            {order.status === "CONFIRMED" && order.purchase_progress && (
              <ProgressCell meta={PURCHASE_PROGRESS_META} value={order.purchase_progress} />
            )}
          </Space>
        }
        extra={
          <Space>
            {/* 发起采购:有 purchase:manage 且单据 CONFIRMED 且未全部下单(评审 S4 补状态门禁)。 */}
            {order.status === "CONFIRMED" && order.purchase_progress !== "FULLY_ORDERED" && (
              <Can perm={Permissions.PURCHASE_MANAGE}>
                <Button type="primary" icon={<ShoppingCartOutlined />} onClick={() => setPurchasing(true)}>
                  发起采购
                </Button>
              </Can>
            )}
            {salesOrderCancellable(order.status) && (
              <Can perm={Permissions.SALES_MANAGE}>
                <Button danger onClick={() => setCancelOpen(true)}>
                  取消销售单
                </Button>
              </Can>
            )}
          </Space>
        }
      >
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="客户">
            {order.customer_display ?? `#${order.customer_id}`}
          </Descriptions.Item>
          <Descriptions.Item label="报价人">
            {order.salesperson_display ?? `#${order.salesperson_id}`}
          </Descriptions.Item>
          <Descriptions.Item label="币种">{order.currency}</Descriptions.Item>
          <Descriptions.Item label="来源报价">
            {order.source_quotation_no ? (
              // 无 quote:manage(报价段路由门)→ 降级纯文本,不点撞 403(DESIGN §7 单据链接降级)。
              <Can
                perm={Permissions.QUOTE_MANAGE}
                fallback={<span>{order.source_quotation_no}</span>}
              >
                <Button
                  type="link"
                  size="small"
                  style={{ padding: 0 }}
                  onClick={() => router.push(`/sales/quotations/${order.source_quotation_id}`)}
                >
                  {order.source_quotation_no}
                </Button>
              </Can>
            ) : (
              "—"
            )}
          </Descriptions.Item>
          <Descriptions.Item label="摘要" span={2}>{order.summary || "—"}</Descriptions.Item>
          <Descriptions.Item label="备注" span={2}>{order.remark || "—"}</Descriptions.Item>
          {order.status === "CANCELLED" && (
            <Descriptions.Item label="取消原因" span={2}>
              {order.cancel_reason || "—"}
              {order.cancelled_at && (
                <span style={{ marginLeft: 12, color: colors.muted }}>
                  {formatDateTime(order.cancelled_at)}
                </span>
              )}
            </Descriptions.Item>
          )}
          {/* 🔴 售价红线:无 receivable:read 者整项不渲染 */}
          {canSeePrice && (
            <Descriptions.Item label="总额" span={2}>
              <span style={{ fontWeight: 600 }}>
                {order.currency} {formatPrice(order.total_amount)}
              </span>
            </Descriptions.Item>
          )}
        </Descriptions>
      </Card>

      <Card title="销售明细">
        <Table<SalesOrderLineOut>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={lines}
          pagination={false}
          scroll={{ x: 1060 }}
        />
      </Card>

      {/* 关联采购单:仅 purchase:read 者的响应带 related_purchase_orders;SALES 无字段则整块不渲染。 */}
      {relatedPOs && (
        <Card title="关联采购单">
          <Table<RelatedPurchaseOrder>
            rowKey="id"
            size="small"
            columns={[
              {
                title: "采购单号",
                dataIndex: "no",
                width: 160,
                render: (v: string, r) => (
                  <Button
                    type="link"
                    size="small"
                    style={{ padding: 0 }}
                    onClick={() => router.push(`/purchasing/orders/${r.id}`)}
                  >
                    {v}
                  </Button>
                ),
              },
              {
                title: "状态",
                dataIndex: "status",
                width: 100,
                render: (s: RelatedPurchaseOrder["status"]) => (
                  <StatusTag meta={PURCHASE_ORDER_STATUS_META} value={s} />
                ),
              },
              { title: "供应商", dataIndex: "supplier_display", ellipsis: true },
              { title: "币种", dataIndex: "currency", width: 70 },
              // 🔴 成本红线:无 purchase:read_cost 者整列不渲染
              ...(canSeeCost
                ? [
                    {
                      title: "金额",
                      dataIndex: "total_amount",
                      width: 130,
                      align: "right" as const,
                      render: (v: RelatedPurchaseOrder["total_amount"]) => formatCost(v),
                    },
                  ]
                : []),
            ]}
            dataSource={relatedPOs}
            pagination={false}
            scroll={{ x: 720 }}
            locale={{ emptyText: "暂无关联采购单" }}
          />
        </Card>
      )}

      {/* 库存/到货:仅 inventory:read 者的响应带 stock_balances;无权者响应无此键,整块不渲染
          (照关联采购单同一模式,前端不自判权限)。含全部行(未到货=0 也列出,对照订购)。 */}
      {stockBalances && (
        <Card title="库存 / 到货">
          <Table<StockBalanceLine>
            rowKey="sku_id"
            size="small"
            columns={[
              { title: "SKU编码", dataIndex: "sku_code", width: 140 },
              { title: "品名", dataIndex: "name", ellipsis: true },
              { title: "规格", dataIndex: "spec_text", ellipsis: true, render: (v) => v || "—" },
              { title: "单位", dataIndex: "unit", width: 70 },
              { title: "订购量", dataIndex: "ordered_qty", width: 90, align: "right",
                render: (v: number | string) => <NumCell value={v} /> },
              { title: "已入库", dataIndex: "inbound_qty", width: 90, align: "right",
                render: (v: number | string) => <NumCell value={v} /> },
              { title: "已出库", dataIndex: "outbound_qty", width: 90, align: "right",
                render: (v: number | string) => <NumCell value={v} /> },
              { title: "可发量", dataIndex: "available_qty", width: 90, align: "right",
                render: (v: number | string) => <NumCell value={v} strong /> },
            ]}
            dataSource={stockBalances}
            pagination={false}
            scroll={{ x: 720 }}
            locale={{ emptyText: "暂无库存数据" }}
          />
        </Card>
      )}

      {/* 关联出库单:仅 outbound:read 者的响应带 related_outbound_orders;无权者无此键,整块不渲染。
          纯仓单,无金额;出库单号链接详情,发运柜链接按 shipment:read 降级(DESIGN §7)。 */}
      {relatedOutbounds && (
        <Card title="关联出库单">
          <Table<RelatedOutboundOrder>
            rowKey="id"
            size="small"
            columns={[
              {
                title: "出库单号",
                dataIndex: "no",
                width: 160,
                render: (v: string, r) => (
                  <Button
                    type="link"
                    size="small"
                    style={{ padding: 0 }}
                    onClick={() => router.push(`/outbound/${r.id}`)}
                  >
                    {v}
                  </Button>
                ),
              },
              {
                title: "发运柜",
                dataIndex: "shipment_no",
                width: 170,
                render: (v: string, r) => {
                  const label = r.container_no || v;
                  return (
                    <Can perm={Permissions.SHIPMENT_READ} fallback={<span>{label}</span>}>
                      <Button
                        type="link"
                        size="small"
                        style={{ padding: 0 }}
                        onClick={() => router.push(`/shipments/${r.shipment_id}`)}
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
                render: (s: RelatedOutboundOrder["status"]) => (
                  <StatusTag meta={OUTBOUND_ORDER_STATUS_META} value={s} />
                ),
              },
              {
                title: "确认时间",
                dataIndex: "issued_at",
                width: 170,
                render: (v: string | null) => (v ? formatDateTime(v) : "—"),
              },
            ]}
            dataSource={relatedOutbounds}
            pagination={false}
            scroll={{ x: 620 }}
            locale={{ emptyText: "暂无关联出库单" }}
          />
        </Card>
      )}

      <PurchaseOrderBuilder
        open={purchasing}
        mode="create"
        sourceSalesOrderId={order.id}
        onClose={() => setPurchasing(false)}
        onSaved={() => {
          setPurchasing(false);
          load();
        }}
      />

      {/* 取消销售单:二次确认讲业务后果 + 留痕原因(DESIGN §7 危险操作)。 */}
      <Modal
        title="取消销售单"
        open={cancelOpen}
        okText="确认取消"
        okButtonProps={{ danger: true }}
        confirmLoading={cancelling}
        onCancel={() => setCancelOpen(false)}
        onOk={async () => {
          setCancelling(true);
          try {
            await salesOrderApi.cancel(id, cancelReason.trim() || null);
            message.success("已取消,来源报价已回到锁档");
            setCancelOpen(false);
            setCancelReason("");
            load();
          } catch (e) {
            // 41802(存在活动采购单)等后端 message 为中文,直显。
            message.error(resolveBizError(e, "取消失败"));
          } finally {
            setCancelling(false);
          }
        }}
      >
        <Space direction="vertical" style={{ width: "100%" }}>
          <span>
            取消后本单进入终态,来源报价回到锁档、可修改后重新转出;
            存在未取消的采购单时本操作会被拒绝。
          </span>
          <Input.TextArea
            rows={2}
            maxLength={500}
            placeholder="取消原因(选填,留痕)"
            value={cancelReason}
            onChange={(e) => setCancelReason(e.target.value)}
          />
        </Space>
      </Modal>
    </Space>
  );
}
