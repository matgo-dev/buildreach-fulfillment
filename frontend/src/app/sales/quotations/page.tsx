"use client";
import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import {
  App,
  Button,
  Input,
  Popconfirm,
  Segmented,
  Space,
  Switch,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { PlusOutlined } from "@ant-design/icons";
import { Can } from "@/components/common/Can";
import { StatusTag } from "@/components/common/StatusTag";
import { ListTable } from "@/components/common/ListTable";
import { ListErrorState } from "@/components/common/ListErrorState";
import { ListPageCard, ListPageBody } from "@/components/common/ListPageCard";
import { useListQuery } from "@/hooks/useListQuery";
import { useAuthStore } from "@/stores/authStore";
import { Permissions } from "@/config/permission-matrix";
import { formatDateTime, formatMoney } from "@/lib/format";
import { resolveBizError } from "@/lib/errorMessages";
import { quotationApi, type QuotationListItem } from "@/lib/quotation";
import {
  QUOTATION_STATUS_META,
  quotationConvertible,
  quotationEditable,
} from "@/lib/quotationStatus";

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
  // 无 quote:manage → 操作整列不渲染(权限=用户级定列去留;状态=行级定单元格内容)。
  const canManage = useAuthStore((s) => s.hasPermission(Permissions.QUOTE_MANAGE));

  const [status, setStatus] = useState("");
  const [keyword, setKeyword] = useState("");
  const [mineOnly, setMineOnly] = useState(false);
  const [sort, setSort] = useState<"created_at" | "total_amount">("created_at");
  const [convertingId, setConvertingId] = useState<number | null>(null);

  const fetcher = useCallback(
    ({ page, size }: { page: number; size: number }) =>
      quotationApi.list({
        status: status || undefined,
        keyword: keyword || undefined,
        salesperson_id: mineOnly && userId ? userId : undefined,
        sort,
        page,
        size,
      }),
    [status, keyword, mineOnly, userId, sort],
  );
  const { rows, setPage, loading, loadError, load, pagination } = useListQuery<QuotationListItem>(
    fetcher,
    { errorMessage: "加载报价列表失败" },
  );

  async function onVoid(id: number) {
    try {
      await quotationApi.void(id);
      message.success("已作废");
      load();
    } catch (e) {
      message.error(resolveBizError(e, "作废失败"));
    }
  }

  async function onConvert(id: number) {
    setConvertingId(id);
    try {
      const { order: so } = await quotationApi.convert(id);
      message.success(`已转销售单 ${so.no}`);
      router.push(`/sales/orders/${so.id}`);
    } catch (e) {
      message.error(resolveBizError(e, "转销售失败"));
    } finally {
      setConvertingId(null);
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
      render: (s: QuotationListItem["status"]) => <StatusTag meta={QUOTATION_STATUS_META} value={s} />,
    },
    { title: "币种", dataIndex: "currency", width: 70 },
    {
      title: "总额",
      dataIndex: "total_amount",
      width: 120,
      align: "right",
      sorter: true,
      render: (v) => formatMoney(v),
    },
    { title: "有效期", dataIndex: "valid_until", width: 110, render: (v) => v || "—" },
    { title: "创建时间", dataIndex: "created_at", width: 170, render: (v: string) => formatDateTime(v) },
    ...(canManage
      ? [
          {
            title: "操作",
            key: "actions",
            width: 220,
            fixed: "right" as const,
            className: "whitespace-nowrap",
            // 行主操作=看详情(点整行,见 onRow);操作列只放编辑/作废/删除,点击不触发行下钻。
            render: (_: unknown, r: QuotationListItem) => (
              <Space size="small" onClick={(e) => e.stopPropagation()}>
                {quotationEditable(r.status) && (
                  <Button
                    type="link"
                    size="small"
                    onClick={() => router.push(`/sales/quotations/${r.id}?edit=1`)}
                  >
                    编辑
                  </Button>
                )}
                {quotationConvertible(r.status) && (
                  <Popconfirm
                    title="转为销售单?"
                    description="转换后此报价进入已转销售终态,并生成销售单。"
                    okText="确认转销售"
                    okButtonProps={{ danger: true }}
                    onConfirm={() => onConvert(r.id)}
                  >
                    <Button type="link" size="small" danger loading={convertingId === r.id}>
                      转销售
                    </Button>
                  </Popconfirm>
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
              </Space>
            ),
          },
        ]
      : []),
  ];

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
      <ListPageBody>
        {loadError && !rows.length ? (
          <ListErrorState onRetry={load} />
        ) : (
          <ListTable<QuotationListItem>
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
            pagination={pagination}
            onChange={(_p, _f, sorter) => {
              const s = Array.isArray(sorter) ? sorter[0] : sorter;
              setSort(s?.field === "total_amount" ? "total_amount" : "created_at");
            }}
          />
        )}
      </ListPageBody>
    </ListPageCard>
  );
}
