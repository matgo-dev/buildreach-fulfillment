"use client";
import { useCallback, useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { Card, Descriptions, Table, Button, Tag, Space, Popconfirm, Spin, App } from "antd";
import type { ColumnsType } from "antd/es/table";
import { catalogApi, SkuDetailItem, SpuDetail, specDisplayText } from "@/lib/catalog";
import { display } from "@/lib/i18n";
import { imageUrl } from "@/lib/image";
import { colors } from "@/lib/tokens";
import { Can } from "@/components/common/Can";
import { SpuForm } from "@/components/catalog/SpuForm";
import { SkuForm } from "@/components/catalog/SkuForm";
import { useAuthStore } from "@/stores/authStore";
import {
  SPU_STATUS_META,
  SKU_STATUS_META,
  spuEditable,
  spuNextAction,
  skuNextActionLabel,
} from "@/lib/productStatus";

export default function SpuDetailPage() {
  const { id } = useParams<{ id: string }>();
  const editParam = useSearchParams().get("edit");
  const { message } = App.useApp();
  const canManage = useAuthStore((s) => s.hasPermission("product:manage"));
  const [spu, setSpu] = useState<SpuDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [editSpu, setEditSpu] = useState(false);
  const [skuForm, setSkuForm] = useState<{ open: boolean; sku?: SkuDetailItem; copyFrom?: SkuDetailItem }>({ open: false });

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
  async function toggleSpu() {
    if (!spu) return;
    const next = spuNextAction(spu.status);
    try {
      await catalogApi.setSpuStatus(spu.id, next.to);
      message.success(`已${next.label}`);
      load();
    } catch (e) {
      // 启用可能因完备性(无带价在售 SKU)被后端拒;停用可能联动 —— 原样透出后端提示。
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
    {
      title: "规格",
      key: "spec",
      // spec_display = SPU 产品级 ∪ SKU 轴(后端读时并集、单一解析),非仅 SKU 自身 spec_jsonb。
      render: (_, r) => specDisplayText(r.spec_display) || "—",
    },
    {
      title: "重量/尺寸",
      key: "physical",
      width: 150,
      render: (_, r) => {
        const parts: string[] = [];
        if (r.weight_kg != null) parts.push(`${r.weight_kg}kg`);
        if (r.length_cm != null && r.width_cm != null && r.height_cm != null)
          parts.push(`${r.length_cm}×${r.width_cm}×${r.height_cm}cm`);
        return parts.length ? parts.join(" · ") : "—";
      },
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 90,
      render: (v: string) => (
        <Tag color={SKU_STATUS_META[v]?.color}>{SKU_STATUS_META[v]?.label ?? v}</Tag>
      ),
    },
    {
      title: "操作",
      width: 220,
      className: "whitespace-nowrap",
      render: (_, r) => (
        <Can perm="product:manage">
          <Space size="small">
            {/* SKU 增改删受父 SPU 锁;上下架(在售/停售)豁免 —— 启用中商品仍可停售单个缺货变体。 */}
            {spuEditable(spu.status) && (
              <Button size="small" type="link" onClick={() => setSkuForm({ open: true, sku: r })}>
                编辑
              </Button>
            )}
            {spuEditable(spu.status) && (
              <Button size="small" type="link" onClick={() => setSkuForm({ open: true, copyFrom: r })}>
                复制
              </Button>
            )}
            <Button size="small" type="link" onClick={() => toggleSku(r)}>
              {skuNextActionLabel(r.status)}
            </Button>
            {spuEditable(spu.status) && (
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
            )}
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
            <Space>
              {/* 编辑仅 DRAFT/INACTIVE(ACTIVE 锁,先停用);启用/停用随状态互斥。 */}
              {spuEditable(spu.status) && <Button onClick={() => setEditSpu(true)}>编辑</Button>}
              <Button
                type={spu.status === "ACTIVE" ? "default" : "primary"}
                onClick={toggleSpu}
              >
                {spuNextAction(spu.status).label}
              </Button>
            </Space>
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
                          border: `1px solid ${colors.line}`,
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
              {
                key: "c",
                label: "分类",
                children: spu.category_path?.length
                  ? spu.category_path.map((c) => display(c.name_i18n)).join(" / ")
                  : spu.category_name_i18n
                    ? display(spu.category_name_i18n)
                    : spu.category_code,
              },
              { key: "b", label: "品牌", children: spu.brand || "—" },
              { key: "h", label: "HS 编码", children: spu.hs_code || "—" },
              {
                key: "s",
                label: "状态",
                children: (
                  <Tag color={SPU_STATUS_META[spu.status].color}>
                    {SPU_STATUS_META[spu.status].label}
                  </Tag>
                ),
              },
              {
                key: "a",
                label: "在售 SKU",
                children: `${spu.skus.filter((s) => s.status === "ACTIVE").length} / 共 ${spu.skus.length} 个`,
              },
              {
                key: "ps",
                label: "产品级规格",
                span: 2,
                children: specDisplayText(spu.spec_display) || "—",
              },
              { key: "d", label: "描述", span: 2, children: spu.description || "—" },
            ]}
          />
        </div>
      </Card>

      <Card
        size="small"
        title="SKU 列表"
        extra={
          <Can perm="product:manage">
            {spuEditable(spu.status) ? (
              <Button type="primary" onClick={() => setSkuForm({ open: true })}>
                新建 SKU
              </Button>
            ) : (
              <Tag color="default">启用中不可增改 SKU,先停用</Tag>
            )}
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
          spuSpec={spu.spec_display}
          sku={skuForm.sku}
          copyFrom={skuForm.copyFrom}
          onClose={() => setSkuForm({ open: false })}
          onSaved={load}
        />
      )}
    </>
  );
}
