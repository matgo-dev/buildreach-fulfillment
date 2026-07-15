"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  App,
  Button,
  Card,
  Input,
  Popconfirm,
  Segmented,
  Space,
  Switch,
  Table,
  Tag,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { PlusOutlined } from "@ant-design/icons";
import { Can } from "@/components/common/Can";
import { useAuthStore } from "@/stores/authStore";
import { Permissions } from "@/config/permission-matrix";
import { quotationApi, type QuotationListItem } from "@/lib/quotation";
import { QUOTATION_STATUS_META, quotationDeletable, quotationEditable } from "@/lib/quotationStatus";

const STATUS_TABS = [
  { label: "全部", value: "" },
  { label: "草稿", value: "DRAFT" },
  { label: "锁档", value: "LOCKED" },
  { label: "已转销售", value: "CONVERTED" },
  { label: "已作废", value: "VOID" },
];

export default function QuotationListPage() {
  const router = useRouter();
  const { message } = App.useApp();
  const userId = useAuthStore((s) => s.user?.id);

  const [rows, setRows] = useState<QuotationListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [keyword, setKeyword] = useState("");
  const [mineOnly, setMineOnly] = useState(false);
  const [sort, setSort] = useState<"created_at" | "total_amount">("created_at");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await quotationApi.list({
        status: status || undefined,
        keyword: keyword || undefined,
        salesperson_id: mineOnly && userId ? userId : undefined,
        sort,
        page,
        size: 20,
      });
      setRows(res.items);
      setTotal(res.total);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "加载报价列表失败");
    } finally {
      setLoading(false);
    }
  }, [status, keyword, mineOnly, userId, sort, page, message]);

  useEffect(() => {
    load();
  }, [load]);

  async function onVoid(id: number) {
    try {
      await quotationApi.void(id);
      message.success("已作废");
      load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "作废失败");
    }
  }

  async function onDelete(id: number) {
    try {
      await quotationApi.del(id);
      message.success("已删除");
      load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "删除失败");
    }
  }

  const columns: ColumnsType<QuotationListItem> = [
    { title: "单号", dataIndex: "no", width: 150 },
    { title: "客户", dataIndex: "customer_display", width: 160, ellipsis: true },
    { title: "报价人", dataIndex: "salesperson_display", width: 100 },
    {
      title: "状态",
      dataIndex: "status",
      width: 110,
      render: (s: QuotationListItem["status"]) => {
        const m = QUOTATION_STATUS_META[s];
        return <Tag color={m.color}>{m.label}</Tag>;
      },
    },
    { title: "币种", dataIndex: "currency", width: 70 },
    {
      title: "总额",
      dataIndex: "total_amount",
      width: 120,
      align: "right",
      sorter: true,
      render: (v) => Number(v).toLocaleString(undefined, { minimumFractionDigits: 2 }),
    },
    { title: "有效期", dataIndex: "valid_until", width: 110, render: (v) => v || "—" },
    { title: "创建时间", dataIndex: "created_at", width: 170, render: (v: string) => v?.replace("T", " ").slice(0, 16) },
    {
      title: "操作",
      key: "actions",
      width: 150,
      fixed: "right",
      className: "whitespace-nowrap",
      // 行主操作=看详情(点整行,见 onRow);操作列只放编辑/作废/删除,点击不触发行下钻。
      render: (_, r) => (
        <Space size="small" onClick={(e) => e.stopPropagation()}>
          <Can perm={Permissions.QUOTE_MANAGE}>
            {quotationEditable(r.status) && (
              <Button
                type="link"
                size="small"
                onClick={() => router.push(`/sales/quotations/${r.id}?edit=1`)}
              >
                编辑
              </Button>
            )}
            {(r.status === "DRAFT" || r.status === "LOCKED") && (
              <Popconfirm
                title="作废该报价?"
                description="作废后不可编辑,可留档备查。"
                okButtonProps={{ danger: true }}
                onConfirm={() => onVoid(r.id)}
              >
                <Button type="link" size="small" danger>
                  作废
                </Button>
              </Popconfirm>
            )}
            {quotationDeletable(r.status) && (
              <Popconfirm
                title="删除草稿?"
                description="草稿将被永久删除,不可恢复。"
                okButtonProps={{ danger: true }}
                onConfirm={() => onDelete(r.id)}
              >
                <Button type="link" size="small" danger>
                  删除
                </Button>
              </Popconfirm>
            )}
          </Can>
        </Space>
      ),
    },
  ];

  return (
    <Card>
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
            placeholder="单号 / 客户名"
            allowClear
            style={{ width: 220 }}
            onSearch={(v) => {
              setKeyword(v);
              setPage(1);
            }}
          />
          <span>
            <Switch size="small" checked={mineOnly} onChange={(c) => { setMineOnly(c); setPage(1); }} />{" "}
            报价人=我
          </span>
        </Space>
        <Can perm={Permissions.QUOTE_MANAGE}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => router.push("/sales/quotations/new")}>
            新建报价
          </Button>
        </Can>
      </Space>
      <Table<QuotationListItem>
        rowKey="id"
        columns={columns}
        dataSource={rows}
        loading={loading}
        scroll={{ x: 1200 }}
        locale={{ emptyText: "暂无报价" }}
        onRow={(r) => ({
          onClick: () => router.push(`/sales/quotations/${r.id}`),
          style: { cursor: "pointer" },
        })}
        pagination={{
          current: page,
          total,
          pageSize: 20,
          showSizeChanger: false,
          showTotal: (t) => `共 ${t} 条`,
          onChange: setPage,
        }}
        onChange={(_p, _f, sorter) => {
          const s = Array.isArray(sorter) ? sorter[0] : sorter;
          setSort(s?.field === "total_amount" ? "total_amount" : "created_at");
        }}
      />
    </Card>
  );
}
