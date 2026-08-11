"use client";
import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { App, Button, Drawer, Empty, Form, Input, Segmented, Select, Space } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { Can } from "@/components/common/Can";
import { StatusTag } from "@/components/common/StatusTag";
import { ListTable } from "@/components/common/ListTable";
import { ListErrorState } from "@/components/common/ListErrorState";
import { ListPageCard, ListPageBody } from "@/components/common/ListPageCard";
import { useListQuery } from "@/hooks/useListQuery";
import { Permissions } from "@/config/permission-matrix";
import { formatDateTime } from "@/lib/format";
import { resolveBizError } from "@/lib/errorMessages";
import { shipmentApi, type ShipmentListItem } from "@/lib/shipment";
import { SHIPMENT_STATUS_META, CONTAINER_TYPE_OPTIONS } from "@/lib/shipmentStatus";
import { LOGISTICS_DISPLAY_ORDER, LOGISTICS_MILESTONE_META } from "@/lib/logisticsMilestone";
import { CUSTOMS_FILTER_OPTIONS, CUSTOMS_STATUS_META } from "@/lib/customsStatus";

// 物流状态下拉筛选项(派生列;镜像展示骨架顺序,单一源头 LOGISTICS_MILESTONE_META)。
const LOGISTICS_FILTER_OPTIONS = [
  { label: "全部物流状态", value: "" },
  ...LOGISTICS_DISPLAY_ORDER.map((m) => ({ label: LOGISTICS_MILESTONE_META[m].label, value: m })),
];

const STATUS_TABS = [
  { label: "全部", value: "" },
  { label: "组柜中", value: "OPEN" },
  { label: "已封柜", value: "LOADED" },
  { label: "已发运", value: "DEPARTED" },
  { label: "已取消", value: "CANCELLED" },
];

export default function ShipmentListPage() {
  const router = useRouter();
  const { message } = App.useApp();
  const [form] = Form.useForm();

  const [status, setStatus] = useState("");
  const [logisticsStatus, setLogisticsStatus] = useState("");
  const [customsStatus, setCustomsStatus] = useState("");
  const [keyword, setKeyword] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);

  const fetcher = useCallback(
    ({ page, size }: { page: number; size: number }) =>
      shipmentApi.list({
        status: status || undefined,
        keyword: keyword || undefined,
        logistics_status: logisticsStatus || undefined,
        customs_status: customsStatus || undefined,
        page,
        size,
      }),
    [status, keyword, logisticsStatus, customsStatus],
  );
  const { rows, setPage, loading, loadError, load, pagination } = useListQuery<ShipmentListItem>(
    fetcher,
    { errorMessage: "加载发运柜列表失败" },
  );

  async function onCreate() {
    const v = await form.validateFields().catch(() => null);
    if (!v) return;
    setCreating(true);
    try {
      const { shipment } = await shipmentApi.create({
        container_no: v.container_no?.trim() || null,
        container_type: v.container_type || null,
        seal_no: v.seal_no?.trim() || null,
      });
      message.success(`已新建发运柜 ${shipment.no}`);
      setCreateOpen(false);
      form.resetFields();
      // 直接进组柜工作台补柜信息 + 添加出库单。
      router.push(`/shipments/${shipment.id}`);
    } catch (e) {
      message.error(resolveBizError(e, "新建失败"));
    } finally {
      setCreating(false);
    }
  }

  const columns: ColumnsType<ShipmentListItem> = [
    { title: "发运柜号", dataIndex: "no", width: 150 },
    {
      title: "柜号",
      dataIndex: "container_no",
      width: 150,
      render: (v: string | null) => v || "—",
    },
    {
      title: "柜型",
      dataIndex: "container_type",
      width: 90,
      render: (v: string | null) => v || "—",
    },
    {
      title: "船名 / 航次",
      key: "vessel",
      width: 180,
      ellipsis: true,
      render: (_, r) =>
        r.vessel_name || r.voyage_no
          ? `${r.vessel_name || "—"}${r.voyage_no ? ` / ${r.voyage_no}` : ""}`
          : "—",
    },
    {
      title: "ETD",
      dataIndex: "etd",
      width: 120,
      render: (v: string | null) => v || "—",
    },
    {
      title: "ATD",
      dataIndex: "atd",
      width: 120,
      render: (v: string | null) => v || "—",
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (s: ShipmentListItem["status"]) => (
        <StatusTag meta={SHIPMENT_STATUS_META} value={s} />
      ),
    },
    {
      title: "物流状态",
      dataIndex: "current_logistics_status",
      width: 110,
      // 纯派生:非 DEPARTED 柜为 null,显「—」;否则已离港/中转/到港徽标。
      render: (v: ShipmentListItem["current_logistics_status"]) =>
        v ? <StatusTag meta={LOGISTICS_MILESTONE_META} value={v} /> : "—",
    },
    {
      title: "报关",
      dataIndex: "customs_status",
      width: 100,
      // 纯派生:OPEN/CANCELLED 柜为 null,显「—」;否则未报关/已申报/已放行徽标。
      render: (v: ShipmentListItem["customs_status"]) =>
        v ? <StatusTag meta={CUSTOMS_STATUS_META} value={v} /> : "—",
    },
    {
      title: "柜内出库单",
      dataIndex: "outbound_count",
      width: 110,
      align: "right",
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
      {/* 工具条统一次序(DESIGN §7):状态 → 搜索。 */}
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
            value={logisticsStatus}
            style={{ width: 150 }}
            options={LOGISTICS_FILTER_OPTIONS}
            onChange={(v) => {
              setLogisticsStatus(v);
              setPage(1);
            }}
          />
          <Select
            value={customsStatus}
            style={{ width: 150 }}
            options={CUSTOMS_FILTER_OPTIONS}
            onChange={(v) => {
              setCustomsStatus(v);
              setPage(1);
            }}
          />
          <Input.Search
            allowClear
            placeholder="发运柜号 / 柜号"
            style={{ width: 240 }}
            defaultValue={keyword}
            onSearch={(v) => {
              setKeyword(v.trim());
              setPage(1);
            }}
          />
        </Space>
        <Can perm={Permissions.SHIPMENT_MANAGE}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            新建柜
          </Button>
        </Can>
      </Space>

      <ListPageBody>
        {loadError && !rows.length ? (
          <ListErrorState onRetry={load} />
        ) : (
          <ListTable<ShipmentListItem>
            rowKey="id"
            columns={columns}
            dataSource={rows}
            loading={loading}
            scroll={{ x: 1400 }}
            locale={{
              emptyText: (
                <Empty description="暂无发运柜">
                  <Can perm={Permissions.SHIPMENT_MANAGE}>
                    <Button
                      type="primary"
                      icon={<PlusOutlined />}
                      onClick={() => setCreateOpen(true)}
                    >
                      新建柜开始组柜
                    </Button>
                  </Can>
                </Empty>
              ),
            }}
            onRow={(r) => ({
              onClick: () => router.push(`/shipments/${r.id}`),
              style: { cursor: "pointer" },
            })}
            pagination={pagination}
          />
        )}
      </ListPageBody>

      {/* 新建柜:柜号/柜型/封条组柜期均可空,后续在工作台补齐。表单走抽屉(DESIGN §5/§11.7)。 */}
      <Drawer
        title="新建发运柜"
        open={createOpen}
        size="min(480px, 92vw)"
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
              新建并组柜
            </Button>
          </Space>
        }
      >
        <Form form={form} layout="vertical">
          <Form.Item name="container_no" label="柜号">
            <Input placeholder="选填,组柜期可留空,后续再填" />
          </Form.Item>
          <Form.Item name="container_type" label="柜型">
            <Select allowClear placeholder="选填" options={[...CONTAINER_TYPE_OPTIONS]} />
          </Form.Item>
          <Form.Item name="seal_no" label="封条号">
            <Input placeholder="选填" />
          </Form.Item>
        </Form>
      </Drawer>
    </ListPageCard>
  );
}
