"use client";
import { useEffect, useMemo, useState } from "react";
import { Alert, App, Button, Drawer, Input, InputNumber, Space, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { RollbackOutlined } from "@ant-design/icons";
import { formatQty } from "@/lib/format";
import { resolveBizError } from "@/lib/errorMessages";
import {
  purchaseReturnApi,
  type PurchaseReturnDetail,
  type PurchaseReturnableLine,
} from "@/lib/purchaseReturn";

interface ReturnRow extends PurchaseReturnableLine {
  qty: number;
}

interface Props {
  open: boolean;
  inboundOrderId: number;
  inboundOrderNo: string;
  onClose: () => void;
  onSaved: (detail: PurchaseReturnDetail) => void;
}

export function PurchaseReturnDrawer({
  open,
  inboundOrderId,
  inboundOrderNo,
  onClose,
  onSaved,
}: Props) {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [rows, setRows] = useState<ReturnRow[]>([]);
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (!open) return;
    setReason("");
    setLoading(true);
    purchaseReturnApi.returnableLines(inboundOrderId)
      .then((res) => {
        setRows(res.items.map((line) => ({
          ...line,
          qty: Number(line.returnable_qty) > 0 ? Number(line.returnable_qty) : 0,
        })));
      })
      .catch((e) => message.error(resolveBizError(e, "加载可退行失败")))
      .finally(() => setLoading(false));
  }, [inboundOrderId, message, open]);

  const selectedQty = useMemo(
    () => rows.reduce((sum, row) => sum + (Number(row.qty) || 0), 0),
    [rows],
  );
  const hasReturnable = rows.some((row) => Number(row.returnable_qty) > 0);

  const columns: ColumnsType<ReturnRow> = [
    { title: "商品", dataIndex: "name_snapshot", ellipsis: true },
    { title: "规格", dataIndex: "spec_text_snapshot", ellipsis: true, render: (v) => v || "—" },
    { title: "单位", dataIndex: "unit_snapshot", width: 70 },
    {
      title: "已入 / 已退 / 退货中 / 可退",
      key: "returnable",
      width: 220,
      align: "right",
      render: (_, r) =>
        `${formatQty(r.received_qty)} / ${formatQty(r.returned_qty)} / ${formatQty(r.in_process_return_qty)} / ${formatQty(r.returnable_qty)}`,
    },
    {
      title: "本次退货",
      dataIndex: "qty",
      width: 140,
      align: "right",
      render: (_, r) => (
        <InputNumber
          min={0}
          max={Number(r.returnable_qty)}
          precision={3}
          value={r.qty}
          style={{ width: 110 }}
          disabled={Number(r.returnable_qty) <= 0}
          onChange={(v) => {
            const qty = Number(v || 0);
            setRows((prev) => prev.map((row) =>
              row.inbound_order_line_id === r.inbound_order_line_id ? { ...row, qty } : row));
          }}
        />
      ),
    },
  ];

  async function submit() {
    const lines = rows
      .filter((row) => Number(row.qty) > 0)
      .map((row, idx) => ({
        inbound_order_line_id: row.inbound_order_line_id,
        qty: Number(row.qty),
        sort_order: idx,
      }));
    if (!lines.length) {
      message.warning("请填写至少一行退货数量");
      return;
    }
    setSaving(true);
    try {
      const detail = await purchaseReturnApi.create({
        inbound_order_id: inboundOrderId,
        reason: reason.trim() || null,
        lines,
      });
      message.success(`已提交采购退货单 ${detail.order.no}`);
      onSaved(detail);
    } catch (e) {
      message.error(resolveBizError(e, "创建采购退货失败"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Drawer
      title="创建采购退货"
      size="large"
      open={open}
      onClose={onClose}
      destroyOnClose
      extra={
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button
            type="primary"
            icon={<RollbackOutlined />}
            loading={saving}
            disabled={!hasReturnable || selectedQty <= 0}
            onClick={submit}
          >
            提交审核
          </Button>
        </Space>
      }
    >
      <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          title={`源入库单 ${inboundOrderNo}`}
          description="提交后进入采购退货审核;审核通过后由仓库确认退货出库,再生成待财务过账的供应商贷项单。"
        />
        <Table<ReturnRow>
          rowKey="inbound_order_line_id"
          size="small"
          loading={loading}
          columns={columns}
          dataSource={rows}
          pagination={false}
          scroll={{ x: 720 }}
        />
        <Space style={{ width: "100%", justifyContent: "space-between" }}>
          <Typography.Text type={hasReturnable ? undefined : "secondary"}>
            本次申请退货数量: {formatQty(selectedQty)}
          </Typography.Text>
        </Space>
        <Input.TextArea
          rows={3}
          placeholder="退货原因(选填,用于采购退货单;后续供应商贷项单会继承该原因)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </Space>
    </Drawer>
  );
}
