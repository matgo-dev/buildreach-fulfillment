"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { App, Button, Card, Descriptions, Input, Modal, Select, Space, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { Can } from "@/components/common/Can";
import { ListErrorState } from "@/components/common/ListErrorState";
import { PageLoading } from "@/components/common/PageLoading";
import { StatusTag } from "@/components/common/StatusTag";
import { Permissions } from "@/config/permission-matrix";
import { resolveBizError } from "@/lib/errorMessages";
import { formatDateTime, formatQty } from "@/lib/format";
import {
  reverseRequestApi,
  type ReverseRequestDetail,
  type ReverseRequestLineOut,
  type ReverseSupplierResolution,
} from "@/lib/reverseRequest";
import {
  REVERSE_GOODS_STATUS_META,
  REVERSE_REQUEST_STATUS_META,
  REVERSE_SUPPLIER_RESOLUTION_LABEL,
  reverseRequestApprovable,
  reverseRequestClosable,
} from "@/lib/reverseRequestStatus";

export default function ReverseRequestDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { message } = App.useApp();
  const id = Number(params.id);

  const [detail, setDetail] = useState<ReverseRequestDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [approveOpen, setApproveOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [completeOpen, setCompleteOpen] = useState(false);
  const [supplierResolution, setSupplierResolution] =
    useState<ReverseSupplierResolution>("SUPPLIER_ACCEPTS_RETURN");
  const [reviewNote, setReviewNote] = useState("");
  const [completionNote, setCompletionNote] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      setDetail(await reverseRequestApi.get(id));
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

  async function act(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      message.success(ok);
      await load();
      return true;
    } catch (e) {
      message.error(resolveBizError(e, "操作失败"));
      return false;
    } finally {
      setBusy(false);
    }
  }

  const columns: ColumnsType<ReverseRequestLineOut> = useMemo(
    () => [
      { title: "#", render: (_, __, i) => i + 1, width: 44 },
      { title: "商品", dataIndex: "name_snapshot", ellipsis: true },
      { title: "规格", dataIndex: "spec_text_snapshot", ellipsis: true, render: (v) => v || "—" },
      { title: "单位", dataIndex: "unit_snapshot", width: 70 },
      { title: "申请数量", dataIndex: "qty", width: 110, align: "right", render: formatQty },
    ],
    [],
  );

  if (loadError && !detail) return <ListErrorState onRetry={load} />;
  if (loading || !detail) return <PageLoading />;

  const { request, lines } = detail;

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      <Card
        title={
          <Space size={8}>
            <Button
              type="text"
              size="small"
              icon={<ArrowLeftOutlined />}
              onClick={() => router.push("/reverse-requests")}
              aria-label="返回列表"
            />
            <span>{request.no}</span>
            <StatusTag meta={REVERSE_REQUEST_STATUS_META} value={request.status} />
          </Space>
        }
        extra={
          <Can perm={Permissions.REVERSE_MANAGE}>
            <Space>
              {reverseRequestApprovable(request.status) && (
                <>
                  <Button danger loading={busy} onClick={() => setRejectOpen(true)}>
                    驳回
                  </Button>
                  <Button type="primary" loading={busy} onClick={() => setApproveOpen(true)}>
                    审核通过
                  </Button>
                </>
              )}
              {reverseRequestClosable(request.status) && (
                <Button type="primary" loading={busy} onClick={() => setCompleteOpen(true)}>
                  关闭申请
                </Button>
              )}
            </Space>
          </Can>
        }
      >
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="类型">出库前履约中取消</Descriptions.Item>
          <Descriptions.Item label="实物状态">
            <StatusTag meta={REVERSE_GOODS_STATUS_META} value={request.goods_status} />
          </Descriptions.Item>
          <Descriptions.Item label="销售单">
            <Can perm={Permissions.SALES_READ} fallback={<span>{request.sales_order_no || "—"}</span>}>
              <Button
                type="link"
                size="small"
                style={{ padding: 0 }}
                onClick={() => router.push(`/sales/orders/${request.sales_order_id}`)}
              >
                {request.sales_order_no || "—"}
              </Button>
            </Can>
          </Descriptions.Item>
          <Descriptions.Item label="客户">{request.customer_display || "—"}</Descriptions.Item>
          <Descriptions.Item label="采购单">
            <Can perm={Permissions.PURCHASE_READ} fallback={<span>{request.purchase_order_no || "—"}</span>}>
              <Button
                type="link"
                size="small"
                style={{ padding: 0 }}
                onClick={() => router.push(`/purchasing/orders/${request.purchase_order_id}`)}
              >
                {request.purchase_order_no || "—"}
              </Button>
            </Can>
          </Descriptions.Item>
          <Descriptions.Item label="供应商">{request.supplier_display || "—"}</Descriptions.Item>
          <Descriptions.Item label="入库单">
            <Can perm={Permissions.INBOUND_READ} fallback={<span>{request.inbound_order_no || "—"}</span>}>
              <Button
                type="link"
                size="small"
                style={{ padding: 0 }}
                onClick={() => router.push(`/inbound/${request.inbound_order_id}`)}
              >
                {request.inbound_order_no || "—"}
              </Button>
            </Can>
          </Descriptions.Item>
          <Descriptions.Item label="处理结论">
            {request.supplier_resolution
              ? REVERSE_SUPPLIER_RESOLUTION_LABEL[request.supplier_resolution]
              : "—"}
          </Descriptions.Item>
          <Descriptions.Item label="申请原因" span={2}>
            {request.reason}
          </Descriptions.Item>
          <Descriptions.Item label="审核备注" span={2}>
            {request.review_note || "—"}
          </Descriptions.Item>
          <Descriptions.Item label="处置说明" span={2}>
            {request.completion_note || "—"}
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">{formatDateTime(request.created_at)}</Descriptions.Item>
          <Descriptions.Item label="审核时间">
            {request.reviewed_at ? formatDateTime(request.reviewed_at) : "—"}
          </Descriptions.Item>
          <Descriptions.Item label="关闭时间">
            {request.completed_at ? formatDateTime(request.completed_at) : "—"}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="申请明细">
        <Table<ReverseRequestLineOut>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={lines}
          pagination={false}
          scroll={{ x: 720 }}
        />
      </Card>

      <Modal
        title="审核通过"
        open={approveOpen}
        okText="确认通过"
        confirmLoading={busy}
        onCancel={() => setApproveOpen(false)}
        onOk={async () => {
          const ok = await act(
            () => reverseRequestApi.approve(id, {
              supplier_resolution: supplierResolution,
              review_note: reviewNote.trim() || null,
            }),
            "已审核通过",
          );
          if (ok) {
            setApproveOpen(false);
            setReviewNote("");
          }
        }}
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Select
            value={supplierResolution}
            style={{ width: "100%" }}
            onChange={setSupplierResolution}
            options={[
              { value: "SUPPLIER_ACCEPTS_RETURN", label: "供应商接受退回" },
              { value: "COMPANY_BEAR_LOSS", label: "供应商不接受,公司承担" },
            ]}
          />
          <Input.TextArea
            rows={3}
            placeholder="审核备注(选填)"
            value={reviewNote}
            onChange={(e) => setReviewNote(e.target.value)}
          />
        </Space>
      </Modal>

      <Modal
        title="驳回申请"
        open={rejectOpen}
        okText="确认驳回"
        okButtonProps={{ danger: true }}
        confirmLoading={busy}
        onCancel={() => setRejectOpen(false)}
        onOk={async () => {
          const ok = await act(
            () => reverseRequestApi.reject(id, { review_note: reviewNote.trim() || null }),
            "已驳回",
          );
          if (ok) {
            setRejectOpen(false);
            setReviewNote("");
          }
        }}
      >
        <Input.TextArea
          rows={3}
          placeholder="驳回原因(选填)"
          value={reviewNote}
          onChange={(e) => setReviewNote(e.target.value)}
        />
      </Modal>

      <Modal
        title="关闭逆向申请"
        open={completeOpen}
        okText="确认关闭"
        confirmLoading={busy}
        onCancel={() => setCompleteOpen(false)}
        onOk={async () => {
          const ok = await act(
            () => reverseRequestApi.complete(id, { completion_note: completionNote.trim() || null }),
            "已关闭",
          );
          if (ok) {
            setCompleteOpen(false);
            setCompletionNote("");
          }
        }}
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <span>
            确认相关线下处置已完成后关闭申请。MVP 阶段不会自动生成退款、冲销、退货或费用单据。
          </span>
          <Input.TextArea
            rows={3}
            placeholder="处置说明(选填)"
            value={completionNote}
            onChange={(e) => setCompletionNote(e.target.value)}
          />
        </Space>
      </Modal>
    </Space>
  );
}
