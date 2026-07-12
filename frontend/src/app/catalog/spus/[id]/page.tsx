"use client";
import { useCallback, useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { Card, Descriptions, Table, Button, Tag, Space, Popconfirm, Spin, App } from "antd";
import type { ColumnsType } from "antd/es/table";
import { catalogApi, SkuDetailItem, SpuDetail } from "@/lib/catalog";
import { display } from "@/lib/i18n";
import { imageUrl } from "@/lib/image";
import { Can } from "@/components/common/Can";
import { SpuForm } from "@/components/catalog/SpuForm";
import { SkuForm } from "@/components/catalog/SkuForm";
import { useAuthStore } from "@/stores/authStore";

function specText(items: SkuDetailItem["spec_jsonb"]): string {
  return (items ?? [])
    .map((i) => `${i.key}:${typeof i.value === "object" ? display(i.value) : i.value}`)
    .join(" / ");
}

export default function SpuDetailPage() {
  const { id } = useParams<{ id: string }>();
  const editParam = useSearchParams().get("edit");
  const { message } = App.useApp();
  const canManage = useAuthStore((s) => s.hasPermission("product:manage"));
  const [spu, setSpu] = useState<SpuDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [editSpu, setEditSpu] = useState(false);
  const [skuForm, setSkuForm] = useState<{ open: boolean; sku?: SkuDetailItem }>({ open: false });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setSpu(await catalogApi.getSpu(Number(id)));
    } catch (e) {
      message.error(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [id, message]);

  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (editParam) setEditSpu(true);
  }, [editParam]);

  if (loading || !spu) return <Spin style={{ display: "block", margin: "80px auto" }} />;

  async function delSku(skuId: number) {
    try {
      await catalogApi.deleteSku(skuId);
      message.success("已删除");
      load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "删除失败");
    }
  }
  async function toggleSku(s: SkuDetailItem) {
    try {
      await catalogApi.setSkuStatus(s.id, s.status === "ACTIVE" ? "INACTIVE" : "ACTIVE");
      message.success("状态已更新");
      load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "操作失败");
    }
  }

  const columns: ColumnsType<SkuDetailItem> = [
    { title: "编码", dataIndex: "sku_code", width: 150 },
    { title: "名称", dataIndex: "name_i18n", render: (v) => display(v) },
    { title: "单位", dataIndex: "unit", width: 80 },
    ...(canManage
      ? [
          {
            title: "参考价",
            dataIndex: "reference_price",
            width: 100,
            render: (v: string | number | null) => v ?? "—",
          } as const,
        ]
      : []),
    { title: "规格", dataIndex: "spec_jsonb", render: (v) => specText(v) || "—" },
    {
      title: "可售",
      dataIndex: "available",
      width: 80,
      render: (v: boolean) => (
        <Tag color={v ? "success" : "default"}>{v ? "可售" : "不可售"}</Tag>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 90,
      render: (v: string) => (
        <Tag color={v === "ACTIVE" ? "success" : "default"}>{v === "ACTIVE" ? "上架" : "下架"}</Tag>
      ),
    },
    {
      title: "操作",
      width: 220,
      className: "whitespace-nowrap",
      render: (_, r) => (
        <Can perm="product:manage">
          <Space size="small">
            <Button size="small" type="link" onClick={() => setSkuForm({ open: true, sku: r })}>
              编辑
            </Button>
            <Button size="small" type="link" onClick={() => toggleSku(r)}>
              {r.status === "ACTIVE" ? "下架" : "上架"}
            </Button>
            <Popconfirm
              title="删除该 SKU?"
              description="逻辑删后从目录隐藏。"
              okText="删除"
              okButtonProps={{ danger: true }}
              cancelText="取消"
              onConfirm={() => delSku(r.id)}
            >
              <Button size="small" type="link" danger>
                删除
              </Button>
            </Popconfirm>
          </Space>
        </Can>
      ),
    },
  ];

  return (
    <>
      <Card
        size="small"
        title={`SPU ${spu.spu_code}`}
        style={{ marginBottom: 16 }}
        extra={
          <Can perm="product:manage">
            <Button onClick={() => setEditSpu(true)}>编辑</Button>
          </Can>
        }
      >
        <div style={{ display: "flex", gap: 24 }}>
          {(() => {
            const cover =
              spu.images.find((i) => i.image_type === "MAIN")?.image_key ??
              spu.images[0]?.image_key;
            if (!cover) return null;
            const rest = spu.images.filter((i) => i.image_key !== cover);
            return (
              <div style={{ flex: "none" }}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={imageUrl(cover, 400)}
                  alt="主图"
                  style={{ width: 160, height: 160, objectFit: "cover", borderRadius: 8 }}
                />
                {rest.length > 0 && (
                  <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap", maxWidth: 160 }}>
                    {rest.map((g) => (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        key={g.id}
                        src={imageUrl(g.image_key, 120)}
                        alt=""
                        title={g.image_type === "DETAIL" ? "详情图" : "轮播图"}
                        style={{
                          width: 36, height: 36, objectFit: "cover", borderRadius: 4,
                          border: "1px solid #dbe4ea",
                        }}
                      />
                    ))}
                  </div>
                )}
              </div>
            );
          })()}
          <Descriptions size="small" column={2} style={{ flex: 1 }}
            items={[
              { key: "n", label: "名称", children: display(spu.name_i18n) },
              { key: "c", label: "分类", children: spu.category_code },
              {
                key: "s",
                label: "状态",
                children: (
                  <Tag color={spu.status === "ACTIVE" ? "success" : "default"}>
                    {spu.status === "ACTIVE" ? "上架" : "下架"}
                  </Tag>
                ),
              },
              {
                key: "a",
                label: "可用 SKU",
                children: spu.has_available_sku ? "有" : "无",
              },
            ]}
          />
        </div>
      </Card>

      <Card
        size="small"
        title="SKU 列表"
        extra={
          <Can perm="product:manage">
            <Button type="primary" onClick={() => setSkuForm({ open: true })}>
              新建 SKU
            </Button>
          </Can>
        }
      >
        <Table
          rowKey="id"
          columns={columns}
          dataSource={spu.skus}
          pagination={false}
          locale={{ emptyText: "暂无 SKU" }}
        />
      </Card>

      <SpuForm open={editSpu} spu={spu} onClose={() => setEditSpu(false)} onSaved={load} />
      {skuForm.open && (
        <SkuForm
          open
          spuId={spu.id}
          categoryCode={spu.category_code}
          sku={skuForm.sku}
          onClose={() => setSkuForm({ open: false })}
          onSaved={load}
        />
      )}
    </>
  );
}
