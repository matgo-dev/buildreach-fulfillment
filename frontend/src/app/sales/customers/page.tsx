"use client";
import { useCallback, useState } from "react";
import {
  App,
  Button,
  Col,
  Descriptions,
  Drawer,
  Form,
  Input,
  Popconfirm,
  Row,
  Segmented,
  Select,
  Space,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { PlusOutlined } from "@ant-design/icons";
import { Can } from "@/components/common/Can";
import { StatusTag } from "@/components/common/StatusTag";
import { ListTable } from "@/components/common/ListTable";
import { ListErrorState } from "@/components/common/ListErrorState";
import { ListPageCard, ListPageBody } from "@/components/common/ListPageCard";
import { useListQuery } from "@/hooks/useListQuery";
import { useCrudDrawer } from "@/hooks/useCrudDrawer";
import { Permissions } from "@/config/permission-matrix";
import { useAuthStore } from "@/stores/authStore";
import { resolveBizError } from "@/lib/errorMessages";
import {
  CUSTOMER_STATUS_META,
  customerApi,
  type CustomerListItem,
  type CustomerOut,
  type CustomerSaveBody,
} from "@/lib/customer";
import { QUOTE_LANGUAGE_OPTIONS, quoteLanguageLabel } from "@/lib/quote-languages";

const STATUS_TABS = [
  { label: "启用", value: "ACTIVE" },
  { label: "停用", value: "INACTIVE" },
  { label: "全部", value: "" },
];

export default function CustomerListPage() {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const canManage = useAuthStore((s) => s.hasPermission(Permissions.CUSTOMER_MANAGE));

  const [status, setStatus] = useState("ACTIVE");
  const [q, setQ] = useState("");
  const [rowBusyId, setRowBusyId] = useState<number | null>(null);

  const fetcher = useCallback(
    ({ page, size }: { page: number; size: number }) =>
      customerApi.list({
        status: status || undefined,
        q: q || undefined,
        page,
        size,
      }),
    [status, q],
  );
  const { rows, setPage, loading, loadError, load, pagination } = useListQuery<CustomerListItem>(
    fetcher,
    { errorMessage: "加载客户列表失败" },
  );

  const drawer = useCrudDrawer<CustomerOut, CustomerSaveBody>({
    form,
    fetchDetail: customerApi.get,
    create: (values) => customerApi.create(values),
    update: (current, values) => customerApi.update(current.id, values),
    afterSubmit: load,
    messages: { created: "已创建", saved: "已保存", loadFailed: "加载客户失败" },
  });
  const { mode, current, saving, openView, openCreate, openEdit, closeDrawer, onSubmit } = drawer;

  async function toggleStatus(r: CustomerListItem) {
    setRowBusyId(r.id);
    try {
      if (r.status === "ACTIVE") {
        await customerApi.deactivate(r.id);
        message.success("已停用");
      } else {
        await customerApi.activate(r.id);
        message.success("已启用");
      }
      load();
    } catch (e) {
      message.error(resolveBizError(e, "操作失败"));
    } finally {
      setRowBusyId(null);
    }
  }

  const columns: ColumnsType<CustomerListItem> = [
    { title: "编码", dataIndex: "code", width: 140 },
    { title: "名称", dataIndex: "name", ellipsis: true },
    {
      title: "报价语言",
      dataIndex: "quote_language",
      width: 110,
      render: (v) => quoteLanguageLabel(v),
    },
    { title: "联系人", dataIndex: "contact_name", width: 140, render: (v) => v || "—" },
    { title: "电话", dataIndex: "contact_phone", width: 140, render: (v) => v || "—" },
    {
      title: "状态",
      dataIndex: "status",
      width: 90,
      render: (s: CustomerListItem["status"]) => <StatusTag meta={CUSTOMER_STATUS_META} value={s} />,
    },
    ...(canManage
      ? [
          {
            title: "操作",
            key: "actions",
            width: 150,
            fixed: "right" as const,
            className: "whitespace-nowrap",
            render: (_: unknown, r: CustomerListItem) => (
              <Space size="small" onClick={(e) => e.stopPropagation()}>
                <Button type="link" size="small" onClick={() => openEdit(r.id)}>
                  编辑
                </Button>
                <Popconfirm
                  title={r.status === "ACTIVE" ? "停用该客户?" : "启用该客户?"}
                  description={
                    r.status === "ACTIVE"
                      ? "停用后不可被新报价选用,历史单据不受影响。"
                      : "启用后可被报价选用。"
                  }
                  onConfirm={() => toggleStatus(r)}
                >
                  <Button type="link" size="small" danger={r.status === "ACTIVE"} loading={rowBusyId === r.id}>
                    {r.status === "ACTIVE" ? "停用" : "启用"}
                  </Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]
      : []),
  ];

  const readOnly = mode === "view";

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
            placeholder="编码 / 名称 / 联系人"
            allowClear
            style={{ width: 240 }}
            onSearch={(v) => {
              setQ(v);
              setPage(1);
            }}
          />
        </Space>
        <Can perm={Permissions.CUSTOMER_MANAGE}>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建客户
          </Button>
        </Can>
      </Space>

      <ListPageBody>
        {loadError && !rows.length ? (
          <ListErrorState onRetry={load} />
        ) : (
          <ListTable<CustomerListItem>
            rowKey="id"
            columns={columns}
            dataSource={rows}
            loading={loading}
            scroll={{ x: 900 }}
            locale={{ emptyText: "暂无客户" }}
            onRow={(r) => ({
              onClick: () => openView(r.id),
              style: { cursor: "pointer" },
            })}
            pagination={pagination}
          />
        )}
      </ListPageBody>

      <Drawer
        title={mode === "create" ? "新建客户" : mode === "edit" ? "编辑客户" : "客户详情"}
        open={mode !== null}
        onClose={closeDrawer}
        width="min(560px, 92vw)"
        destroyOnClose
        extra={
          readOnly && canManage && current ? (
            <Button type="primary" onClick={() => openEdit(current.id)}>
              编辑
            </Button>
          ) : null
        }
        footer={
          readOnly ? null : (
            <Space style={{ width: "100%", justifyContent: "flex-end" }}>
              <Button onClick={closeDrawer} disabled={saving}>
                取消
              </Button>
              <Button type="primary" loading={saving} onClick={onSubmit}>
                保存
              </Button>
            </Space>
          )
        }
      >
        {readOnly ? (
          current ? (
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="编码">{current.code}</Descriptions.Item>
              <Descriptions.Item label="名称">{current.name}</Descriptions.Item>
              <Descriptions.Item label="报价语言">
                {quoteLanguageLabel(current.quote_language)}
              </Descriptions.Item>
              <Descriptions.Item label="联系人">{current.contact_name || "—"}</Descriptions.Item>
              <Descriptions.Item label="电话">{current.contact_phone || "—"}</Descriptions.Item>
              <Descriptions.Item label="邮箱">{current.contact_email || "—"}</Descriptions.Item>
              <Descriptions.Item label="地址">{current.address || "—"}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <StatusTag meta={CUSTOMER_STATUS_META} value={current.status} />
              </Descriptions.Item>
            </Descriptions>
          ) : null
        ) : (
          <Form form={form} layout="vertical">
            <Form.Item name="name" label="名称" rules={[{ required: true, message: "请输入客户名称" }]}>
              <Input maxLength={200} placeholder="客户名称" />
            </Form.Item>
            <Form.Item name="quote_language" label="报价语言" extra="不填=建报价时默认中文">
              <Select allowClear placeholder="可空" options={QUOTE_LANGUAGE_OPTIONS} />
            </Form.Item>
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item name="contact_name" label="联系人">
                  <Input maxLength={100} placeholder="选填" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="contact_phone" label="电话">
                  <Input maxLength={30} placeholder="选填" />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item name="contact_email" label="邮箱" rules={[{ type: "email", message: "邮箱格式不正确" }]}>
              <Input maxLength={255} placeholder="选填" />
            </Form.Item>
            <Form.Item name="address" label="地址" style={{ marginBottom: 0 }}>
              <Input.TextArea rows={2} maxLength={255} placeholder="选填" />
            </Form.Item>
          </Form>
        )}
      </Drawer>
    </ListPageCard>
  );
}
