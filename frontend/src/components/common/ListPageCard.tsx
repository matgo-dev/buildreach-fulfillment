"use client";
import type { CSSProperties, ReactNode } from "react";
import { Card } from "antd";
import type { CardProps } from "antd";

/**
 * 列表页外壳 —— 固定外壳布局下承载「工具条固定 + 表体内滚」的定高 flex 容器。
 *
 * 与 ListTable 配对:ListTable 要求父级是「确定高度 + flex 列 + minHeight:0」才能量对表体高度。
 * 把这个契约收进本组件,新列表页用它即自动满足,不再每页手抄 —— 杜绝漏写 minHeight:0 导致表体不滚的静默 bug。
 *
 * 用法:第一个子节点放工具条(自然占高、固定在顶),表区用 <ListPageBody> 包住(撑满剩余高、内部滚动):
 *   <ListPageCard>
 *     <Space>…工具条…</Space>
 *     <ListPageBody>{loadError ? <ListErrorState /> : <ListTable … />}</ListPageBody>
 *   </ListPageCard>
 * size="small" 等原生 Card 属性照常透传;style / styles.body 会与本组件的定高样式合并(调用方覆盖优先)。
 * 不传 title:列表页标题由面包屑承担;且 body 的 height:100% 未扣 Card header,传 title 会纵向溢出
 * (真出现带头场景时再扩展本组件,勿在调用方打补丁)。
 */
/** Card 的 styles 语义分区对象形态(不含函数形态 —— 本组件调用方均传对象,不传函数)。 */
type CardSemanticStyles = {
  root?: CSSProperties;
  header?: CSSProperties;
  body?: CSSProperties;
  extra?: CSSProperties;
  title?: CSSProperties;
  actions?: CSSProperties;
  cover?: CSSProperties;
};

type ListPageCardProps = Omit<CardProps, "styles"> & { styles?: CardSemanticStyles };

export function ListPageCard({ children, style, styles, ...rest }: ListPageCardProps) {
  return (
    <Card
      {...rest}
      style={{ height: "100%", ...style }}
      styles={{
        ...styles,
        body: {
          height: "100%",
          display: "flex",
          flexDirection: "column",
          minHeight: 0,
          ...styles?.body,
        },
      }}
    >
      {children}
    </Card>
  );
}

/** 表区容器:撑满 ListPageCard 剩余高度、内部滚动 —— ListTable 的直接父级(提供其所需的确定高度)。 */
export function ListPageBody({ children }: { children: ReactNode }) {
  return <div style={{ flex: "1 1 auto", minHeight: 0 }}>{children}</div>;
}
