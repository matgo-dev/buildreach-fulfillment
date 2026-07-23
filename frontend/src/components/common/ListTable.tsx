"use client";
import { useEffect, useRef, useState } from "react";
import { Table } from "antd";
import type { TableProps } from "antd";

/**
 * 列表页统一表格 —— 「固定外壳 + 表体内滚」的唯一承载点。
 *
 * 形态(密集 ERP 行业标准,SAP Fiori / NetSuite / Linear / Gmail):面包屑 + 工具条 + 表头全锁死,
 * 只有数据行在有界区域内上下滚。落地机制 = AntD Table `scroll.y`(表头/分页固定、body 内滚)。
 *
 * scroll.y 需要一个像素高度,不能给百分比;故本组件用 ResizeObserver 测量自身可用高度
 * (容器高 − 表头高 − 分页高)动态喂给 scroll.y。这套 fiddly 计算**只在这里一处**,各列表页零心智负担。
 *
 * 用法契约:放在一个**有确定高度**的容器里(通常是 flex 列的 flex-1 min-h-0 子项);
 * 组件自身撑满该容器(height:100%)。横向 scroll.x 照常透传,与内部 y 合并。
 * 仅用于「页级主列表」;抽屉/弹窗内的短表仍用原生 Table。
 */
export function ListTable<RecordType = Record<string, unknown>>({
  scroll,
  ...rest
}: TableProps<RecordType>) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [bodyH, setBodyH] = useState<number>();

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const measure = () => {
      const headH = wrap.querySelector<HTMLElement>(".ant-table-thead")?.offsetHeight ?? 0;
      const pagerEl = wrap.querySelector<HTMLElement>(".ant-table-pagination");
      const pagerH = pagerEl ? pagerEl.offsetHeight + 16 : 0; // + 分页上下外边距
      const avail = wrap.clientHeight - headH - pagerH;
      setBodyH(avail > 40 ? avail : undefined);
    };
    const ro = new ResizeObserver(measure);
    ro.observe(wrap);
    measure();
    return () => ro.disconnect();
  }, []);

  return (
    <div ref={wrapRef} style={{ height: "100%", minHeight: 0, overflow: "hidden" }}>
      <Table<RecordType> {...rest} scroll={{ ...scroll, y: bodyH }} />
    </div>
  );
}
