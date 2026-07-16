"use client";
import { useCallback, useEffect, useState } from "react";
import {
  Table,
  Input,
  Segmented,
  Button,
  Tag,
  Space,
  Tooltip,
  Popconfirm,
  Row,
  Col,
  Card,
  App,
} from "antd";
import { PlusOutlined, WarningOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useRouter } from "next/navigation";
import { catalogApi, SpuListItem } from "@/lib/catalog";
import { display } from "@/lib/i18n";
import { Can } from "@/components/common/Can";
import { useAuthStore } from "@/stores/authStore";
import { CategoryTree } from "@/components/catalog/CategoryTree";
import { SPU_STATUS_META, spuEditable, spuDeletable, spuNextAction } from "@/lib/productStatus";

const PAGE_SIZE = 20;

export default function SpuListPage() {
  const { message } = App.useApp();
  const router = useRouter();
  // 无 product:manage → 整列不渲染(权限=用户级,列去留;状态=行级,单元格内差异)。
  const canManage = useAuthStore((s) => s.hasPermission("product:manage"));
  const [rows, setRows] = useState<SpuListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [keyword, setKeyword] = useState("");
  const [status, setStatus] = useState<string>("ALL");
  const [category, setCategory] = useState<string | undefined>();
  const [categoryLeaf, setCategoryLeaf] = useState(false); // 选中是叶子时,「新建 SPU」预填该分类
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await catalogApi.listSpus({
        keyword,
        status: status === "ALL" ? undefined : status,
        category_code: category,
        page,
        size: PAGE_SIZE,
      });
      setRows(r.items);
      setTotal(r.total);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [keyword, status, category, page, message]);

  useEffect(() => {
    load();
  }, [load]);

  async function onDelete(id: number) {
    try {
      await catalogApi.deleteSpu(id);
      message.success("已删除");
      load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "删除失败");
    }
  }
  async function onToggle(s: SpuListItem) {
    const next = spuNextAction(s.status);
    try {
      await catalogApi.setSpuStatus(s.id, next.to);
      message.success(`已${next.label}`);
      load();
    } catch (e) {
      // 启用可能因完备性(无带价在售 SKU)被后端拒,原样透出后端提示。
      message.error(e instanceof Error ? e.message : "操作失败");
    }
  }

  const columns: ColumnsType<SpuListItem> = [
    { title: "编码", dataIndex: "spu_code", width: 150 },
    {
      title: "名称",
      dataIndex: "name_i18n",
      render: (v, r) => (
        <Space>
          <span>{display(v)}</span>
          {!r.has_active_sku && (
            <Tooltip title="该商品下无在售 SKU,无法启用 / 被报价选用">
              <Tag icon={<WarningOutlined />} color="warning">
                无在售 SKU
              </Tag>
            </Tooltip>
          )}
        </Space>
      ),
    },
    {
      title: "分类",
      dataIndex: "category_name_i18n",
      width: 150,
      render: (v: SpuListItem["category_name_i18n"], r) =>
        v ? display(v) : r.category_code,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 90,
      render: (v: SpuListItem["status"]) => (
        <Tag color={SPU_STATUS_META[v].color}>{SPU_STATUS_META[v].label}</Tag>
      ),
    },
    ...(canManage
      ? [
          {
            title: "操作",
            width: 200,
            className: "whitespace-nowrap",
            render: (_: unknown, r: SpuListItem) => (
              <Space size="small" onClick={(e) => e.stopPropagation()}>
                {/* 编辑/删除仅 DRAFT/INACTIVE 可见(ACTIVE 锁,先停用);启用/停用随状态互斥。 */}
                {spuEditable(r.status) && (
                  <Button
                    size="small"
                    type="link"
                    onClick={() => router.push(`/catalog/spus/${r.id}?edit=1`)}
                  >
                    编辑
                  </Button>
                )}
                <Button size="small" type="link" onClick={() => onToggle(r)}>
                  {spuNextAction(r.status).label}
                </Button>
                {spuDeletable(r.status) && (
                  <Popconfirm
                    title="删除该 SPU?"
                    description="逻辑删后从目录隐藏(仍有未删 SKU 时不可删)。"
                    okText="删除"
                    okButtonProps={{ danger: true }}
                    cancelText="取消"
                    onConfirm={() => onDelete(r.id)}
                  >
                    <Button size="small" type="link" danger>
                      删除
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
    <Row gutter={16}>
      <Col flex="240px">
        <Card size="small" title="分类">
          <CategoryTree
            onSelect={(c, isLeaf) => {
              setCategory(c);
              setCategoryLeaf(isLeaf);
              setPage(1);
            }}
          />
        </Card>
      </Col>
      <Col flex="auto" style={{ minWidth: 0 }}>
        <Card size="small">
          {/* 工具条统一次序(DESIGN §7):状态 → 搜索。 */}
          <Space style={{ marginBottom: 12 }} wrap>
            <Segmented
              value={status}
              onChange={(k) => {
                setStatus(k as string);
                setPage(1);
              }}
              options={[
                { label: "全部", value: "ALL" },
                { label: "草稿", value: "DRAFT" },
                { label: "启用", value: "ACTIVE" },
                { label: "停用", value: "INACTIVE" },
              ]}
            />
            <Input.Search
              placeholder="名称 / 编码"
              allowClear
              style={{ width: 240 }}
              onSearch={(v) => {
                setKeyword(v);
                setPage(1);
              }}
            />
            <Can perm="product:manage">
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() =>
                  router.push(
                    category
                      ? `/catalog/spus/new?category=${encodeURIComponent(category)}&leaf=${categoryLeaf ? 1 : 0}`
                      : "/catalog/spus/new",
                  )
                }
              >
                新建 SPU
              </Button>
            </Can>
          </Space>
          <Table
            rowKey="id"
            loading={loading}
            columns={columns}
            dataSource={rows}
            onRow={(r) => ({
              onClick: () => router.push(`/catalog/spus/${r.id}`),
              style: { cursor: "pointer" },
            })}
            pagination={{
              current: page,
              total,
              pageSize: PAGE_SIZE,
              onChange: setPage,
              showSizeChanger: false,
              showTotal: (t) => `共 ${t} 条`,
            }}
            locale={{ emptyText: "暂无 SPU" }}
          />
        </Card>
      </Col>
    </Row>
  );
}
