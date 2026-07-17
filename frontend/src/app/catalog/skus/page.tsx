"use client";
import { useState } from "react";
import { Card, Input, Table, Tag, App } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useRouter } from "next/navigation";
import { catalogApi, SkuSearchItem, specAxisText } from "@/lib/catalog";
import { display } from "@/lib/i18n";
import { SKU_STATUS_META } from "@/lib/productStatus";

export default function SkuSearchPage() {
  const { message } = App.useApp();
  const router = useRouter();
  const [rows, setRows] = useState<SkuSearchItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  async function onSearch(q: string) {
    if (!q.trim()) {
      setRows([]);
      setSearched(false);
      return;
    }
    setLoading(true);
    try {
      const r = await catalogApi.searchSkus({ q: q.trim(), page: 1, size: 50 });
      setRows(r.items);
      setSearched(true);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "搜索失败");
    } finally {
      setLoading(false);
    }
  }

  const columns: ColumnsType<SkuSearchItem> = [
    { title: "编码", dataIndex: "sku_code", width: 150 },
    { title: "名称", dataIndex: "name_i18n", render: (v) => display(v) },
    { title: "单位", dataIndex: "unit", width: 80 },
    { title: "规格", dataIndex: "spec_display", render: (_, r) => specAxisText(r.spec_display) || "—" },
    {
      title: "状态",
      dataIndex: "status",
      width: 90,
      render: (v: string) => (
        <Tag color={SKU_STATUS_META[v]?.color}>{SKU_STATUS_META[v]?.label ?? v}</Tag>
      ),
    },
  ];

  return (
    <Card size="small">
      <Input.Search
        placeholder="按名称 / 规格 / 编码模糊搜"
        allowClear
        enterButton
        style={{ maxWidth: 440, marginBottom: 12 }}
        onSearch={onSearch}
      />
      <Table
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={false}
        locale={{ emptyText: searched ? "无匹配 SKU" : "输入关键词搜索" }}
        onRow={(r) => ({
          onClick: () => router.push(`/catalog/spus/${r.spu_id}`),
          style: { cursor: "pointer" },
        })}
      />
    </Card>
  );
}
