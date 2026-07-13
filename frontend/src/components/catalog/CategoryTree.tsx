"use client";
import { useEffect, useState } from "react";
import { Tree, Spin, Empty } from "antd";
import type { DataNode } from "antd/es/tree";
import { catalogApi, CategoryNode } from "@/lib/catalog";
import { display } from "@/lib/i18n";

// 扁平激活分类组装成树。任意层级可选(Addendum C:选父类→按整棵子树过滤;
// 归属仍限叶子,由 SpuForm 的 TreeSelect 单独约束)。
function buildTree(nodes: CategoryNode[]): DataNode[] {
  const byParent = new Map<string | null, CategoryNode[]>();
  nodes.forEach((n) => {
    const arr = byParent.get(n.parent_code) ?? [];
    arr.push(n);
    byParent.set(n.parent_code, arr);
  });
  const make = (parent: string | null): DataNode[] =>
    (byParent.get(parent) ?? []).map((n) => ({
      key: n.code,
      title: display(n.name_i18n) || n.code,
      isLeaf: n.is_leaf,
      children: n.is_leaf ? undefined : make(n.code),
    }));
  return make(null);
}

/** 左侧分类树:选中任意节点回传 code(子树过滤);再点一次取消选中回传 undefined。 */
export function CategoryTree({ onSelect }: { onSelect: (code: string | undefined) => void }) {
  const [data, setData] = useState<DataNode[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    catalogApi
      .categoriesTree()
      .then((r) => {
        if (alive) setData(buildTree(r.items));
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  if (loading) return <Spin style={{ padding: 16 }} />;
  if (data.length === 0) return <Empty description="暂无分类" image={Empty.PRESENTED_IMAGE_SIMPLE} />;

  return (
    <Tree
      treeData={data}
      showLine
      blockNode
      onSelect={(keys) => onSelect(keys[0] as string | undefined)}
    />
  );
}
