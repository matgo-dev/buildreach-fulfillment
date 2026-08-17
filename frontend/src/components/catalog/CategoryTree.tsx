"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { Tree, Spin, Empty, Input } from "antd";
import type { DataNode } from "antd/es/tree";
import { catalogApi, CategoryNode } from "@/lib/catalog";
import { display } from "@/lib/i18n";
import { colors } from "@/lib/tokens";

// 命中片段染品牌色加粗(大小写不敏感,取首个匹配)。
function highlight(text: string, kw: string) {
  const i = text.toLowerCase().indexOf(kw.toLowerCase());
  if (i < 0) return text;
  return (
    <>
      {text.slice(0, i)}
      <span style={{ color: colors.brand, fontWeight: 600 }}>{text.slice(i, i + kw.length)}</span>
      {text.slice(i + kw.length)}
    </>
  );
}

// 点分 code 的祖先前缀:"08.005.019" → ["08","08.005"](与后端祖先链同一套约定)。
function ancestorsOf(code: string): string[] {
  const parts = code.split(".");
  return parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join("."));
}

// 扁平激活分类组装成树。kw 非空时保留:命中节点 + 其祖先链(展开到命中项)+ 其后代子树
// (命中父节点可继续下钻);命中的父节点自动展开露出子树。title 高亮。
function buildTree(nodes: CategoryNode[], kw: string): { data: DataNode[]; expanded: string[] } {
  const label = (n: CategoryNode) => display(n.name_i18n) || n.code;
  let keep: Set<string> | null = null;
  const expanded = new Set<string>();
  if (kw) {
    const q = kw.toLowerCase();
    const matched = new Set<string>();
    for (const n of nodes) {
      if (label(n).toLowerCase().includes(q) || n.code.toLowerCase().includes(q)) {
        matched.add(n.code);
        if (!n.is_leaf) expanded.add(n.code); // 命中的是父节点 → 展开露出它的子树
      }
    }
    keep = new Set(matched);
    for (const code of matched) {
      for (const a of ancestorsOf(code)) {
        keep.add(a);
        expanded.add(a); // 展开到命中项的整条祖先链
      }
    }
    // 命中父节点的后代也保留,否则展开后为空(用户点 [+] 看着像没反应)。
    for (const n of nodes) {
      if (keep.has(n.code)) continue;
      for (const a of ancestorsOf(n.code)) {
        if (matched.has(a)) {
          keep.add(n.code);
          break;
        }
      }
    }
  }
  const byParent = new Map<string | null, CategoryNode[]>();
  nodes.forEach((n) => {
    if (keep && !keep.has(n.code)) return;
    const arr = byParent.get(n.parent_code) ?? [];
    arr.push(n);
    byParent.set(n.parent_code, arr);
  });
  const make = (parent: string | null): DataNode[] =>
    (byParent.get(parent) ?? []).map((n) => ({
      key: n.code,
      title: kw ? highlight(label(n), kw) : label(n),
      isLeaf: n.is_leaf,
      children: n.is_leaf ? undefined : make(n.code),
    }));
  return { data: make(null), expanded: Array.from(expanded) };
}

/** 左侧分类树:顶部搜索框实时过滤(命中分支+祖先,自动展开高亮);选中任意节点回传 code
 *  (子树过滤)+ 是否叶子(供「新建 SPU」预填分类),再点一次取消选中回传 undefined/false。 */
export function CategoryTree({
  onSelect,
}: {
  onSelect: (code: string | undefined, isLeaf: boolean) => void;
}) {
  const [nodes, setNodes] = useState<CategoryNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [kw, setKw] = useState("");
  const [expandedKeys, setExpandedKeys] = useState<string[]>([]);
  const [autoExpandParent, setAutoExpandParent] = useState(true);
  const treeViewportRef = useRef<HTMLDivElement | null>(null);
  const [treeHeight, setTreeHeight] = useState(520);

  useEffect(() => {
    let alive = true;
    catalogApi
      .categoriesTree()
      .then((r) => {
        if (alive) setNodes(r.items);
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const el = treeViewportRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const syncHeight = () => setTreeHeight(Math.max(240, Math.floor(el.clientHeight)));
    syncHeight();
    const ro = new ResizeObserver(syncHeight);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const q = kw.trim();
  const { data, expanded } = useMemo(() => buildTree(nodes, q), [nodes, q]);

  // 搜索时用算出的祖先展开集;清空时收起回一级。手动展开/收起由 onExpand 接管(不受此影响)。
  useEffect(() => {
    setExpandedKeys(q ? expanded : []);
    setAutoExpandParent(true);
  }, [q, expanded]);

  return (
    <div style={{ height: "100%", minHeight: 0, display: "flex", flexDirection: "column" }}>
      {!loading && (
        <Input.Search
          placeholder="搜索分类"
          allowClear
          size="small"
          style={{ marginBottom: 8 }}
          value={kw}
          onChange={(e) => setKw(e.target.value)}
        />
      )}
      <div ref={treeViewportRef} style={{ flex: "1 1 auto", minHeight: 0 }}>
        {loading ? (
          <Spin style={{ padding: 16 }} />
        ) : data.length === 0 ? (
          <Empty
            description={q ? "无匹配分类" : "暂无分类"}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        ) : (
          <Tree
            treeData={data}
            showLine
            blockNode
            height={treeHeight}
            expandedKeys={expandedKeys}
            autoExpandParent={autoExpandParent}
            onExpand={(keys) => {
              setExpandedKeys(keys as string[]);
              setAutoExpandParent(false);
            }}
            onSelect={(keys, info) =>
              onSelect(keys[0] as string | undefined, !!(info.node as DataNode).isLeaf)
            }
          />
        )}
      </div>
    </div>
  );
}
