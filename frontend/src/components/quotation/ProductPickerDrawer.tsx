"use client";
import { useCallback, useMemo, useRef, useState } from "react";
import { Button, Drawer, Empty, Input, List, Space, Spin, Tag } from "antd";
import { CheckOutlined, PlusOutlined } from "@ant-design/icons";
import { catalogApi, type SkuSearchItem } from "@/lib/catalog";
import { display } from "@/lib/i18n";
import { imageUrl } from "@/lib/image";
import { colors } from "@/lib/tokens";

/** 选中回传:报价行需要的最小信息(id + 展示名 + 单位 code)。 */
export interface PickedSku {
  sku_id: number;
  sku_code: string;
  name: string;
  unit: string;
}

/**
 * 报价选货抽屉:搜「可选货」(available=true → SKU/SPU 均 ACTIVE 未删),逐条添加、可连加多件。
 * 已在单据上的 SKU 标「已添加」不可重复加(改数量在行内)。红线:reference_price 不展示(此处也不取成本)。
 * 载体=右侧抽屉(DESIGN Rule 7:挑选/表单优先抽屉),配色走平台主色,不抄前台 Mall 绿。
 */
export function ProductPickerDrawer({
  open,
  addedSkuIds,
  onClose,
  onPick,
}: {
  open: boolean;
  addedSkuIds: Set<number>;
  onClose: () => void;
  onPick: (sku: PickedSku) => void;
}) {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<SkuSearchItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const seq = useRef(0);

  const doSearch = useCallback((kw: string) => {
    const mine = ++seq.current;
    if (!kw.trim()) {
      setItems([]);
      setSearched(false);
      return;
    }
    setLoading(true);
    catalogApi
      .searchSkus({ q: kw, available: true, page: 1, size: 30 })
      .then((page) => {
        if (mine === seq.current) {
          setItems(page.items);
          setSearched(true);
        }
      })
      .catch(() => {
        if (mine === seq.current) {
          setItems([]);
          setSearched(true);
        }
      })
      .finally(() => {
        if (mine === seq.current) setLoading(false);
      });
  }, []);

  // 300ms 防抖,边打边搜。
  const debounced = useMemo(() => {
    let t: ReturnType<typeof setTimeout>;
    return (kw: string) => {
      clearTimeout(t);
      t = setTimeout(() => doSearch(kw), 300);
    };
  }, [doSearch]);

  const body = () => {
    if (loading) return <Spin style={{ display: "block", marginTop: 48 }} />;
    if (!searched)
      return <Empty description="输入关键词搜索可选货" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ marginTop: 48 }} />;
    if (items.length === 0)
      return <Empty description="无可选货(SKU 与其 SPU 需均为启用)" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ marginTop: 48 }} />;
    return (
      <List
        dataSource={items}
        renderItem={(it) => {
          const added = addedSkuIds.has(it.id);
          const img = imageUrl(it.spu_main_image, 80);
          return (
            <List.Item
              actions={[
                added ? (
                  <Tag color="success" icon={<CheckOutlined />}>
                    已添加
                  </Tag>
                ) : (
                  <Button
                    type="link"
                    icon={<PlusOutlined />}
                    onClick={() =>
                      onPick({ sku_id: it.id, sku_code: it.sku_code, name: display(it.name_i18n), unit: it.unit })
                    }
                  >
                    添加
                  </Button>
                ),
              ]}
            >
              <List.Item.Meta
                avatar={
                  <div
                    style={{
                      width: 48,
                      height: 48,
                      borderRadius: 6,
                      border: `1px solid ${colors.line}`,
                      background: colors.bg,
                      overflow: "hidden",
                      flex: "none",
                    }}
                  >
                    {img ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={img} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                    ) : null}
                  </div>
                }
                title={<span style={{ color: colors.ink }}>{display(it.name_i18n)}</span>}
                description={
                  <Space size="large" style={{ color: colors.muted, fontSize: 12 }}>
                    <span>{it.sku_code}</span>
                    <span>单位: {it.unit}</span>
                  </Space>
                }
              />
            </List.Item>
          );
        }}
      />
    );
  };

  return (
    <Drawer
      open={open}
      onClose={onClose}
      size={560}
      title="选择商品"
      extra={
        <Button type="primary" onClick={onClose}>
          完成
        </Button>
      }
    >
      <Input.Search
        placeholder="输入编号 / 名称 / 品牌 / 规格搜索"
        allowClear
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          debounced(e.target.value);
        }}
        onSearch={doSearch}
        style={{ marginBottom: 16 }}
      />
      {body()}
    </Drawer>
  );
}
