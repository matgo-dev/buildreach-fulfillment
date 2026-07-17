"use client";
import { Spin } from "antd";

/** 详情/编辑页加载守卫的统一占位(多数派样式:块级 + 顶距 80)。 */
export function PageLoading() {
  return <Spin style={{ display: "block", marginTop: 80 }} />;
}
