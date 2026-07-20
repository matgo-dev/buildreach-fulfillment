"use client";
import { useCallback, useEffect, useState } from "react";
import { App, Card, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { CheckOutlined } from "@ant-design/icons";
import { PageLoading } from "@/components/common/PageLoading";
import { ListErrorState } from "@/components/common/ListErrorState";
import { resolveBizError } from "@/lib/errorMessages";
import { roleApi, type RoleOut } from "@/lib/role";
import { colors } from "@/lib/tokens";

// 模块分组顺序 + 中文标签(镜像后端 rbac/constants.py ModuleLabel;单页使用,不抽共享配置)。
const MODULE_ORDER = ["auth", "system", "fulfillment"] as const;
const MODULE_LABEL: Record<string, string> = {
  auth: "会话",
  system: "系统",
  fulfillment: "履约业务",
};

interface PermissionRow {
  code: string;
  name: string;
  module: string;
  byRole: Record<string, boolean>;
}

export default function RolePermissionMatrixPage() {
  const { message } = App.useApp();
  const [roles, setRoles] = useState<RoleOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      setRoles(await roleApi.list());
    } catch (e) {
      setLoadError(true);
      message.error(resolveBizError(e, "加载角色权限矩阵失败"));
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !roles.length) return <PageLoading />;
  if (loadError && !roles.length) return <ListErrorState onRetry={load} />;

  // 按权限点 code 去重合并所有角色的权限点集合,拼出 权限点 × 角色 矩阵。
  const permIndex = new Map<string, PermissionRow>();
  roles.forEach((role) => {
    role.permissions.forEach((p) => {
      const row = permIndex.get(p.code) ?? { code: p.code, name: p.name, module: p.module, byRole: {} };
      row.byRole[role.code] = true;
      permIndex.set(p.code, row);
    });
  });

  const columns: ColumnsType<PermissionRow> = [
    {
      title: "权限点",
      dataIndex: "name",
      width: 220,
      render: (name: string, r) => (
        <span>
          {name}
          <span style={{ color: colors.muted, marginLeft: 8, fontSize: 12 }}>{r.code}</span>
        </span>
      ),
    },
    ...roles.map((role) => ({
      title: (
        <span>
          {role.name}
          <span style={{ color: colors.muted, marginLeft: 6, fontSize: 12 }}>{role.code}</span>
        </span>
      ),
      key: role.code,
      width: 150,
      align: "center" as const,
      render: (_: unknown, r: PermissionRow) =>
        r.byRole[role.code] ? <CheckOutlined style={{ color: colors.success }} /> : (
          <span style={{ color: colors.muted }}>—</span>
        ),
    })),
  ];

  return (
    <Card>
      <Typography.Paragraph style={{ color: colors.muted, marginBottom: 24 }}>
        只读展示各角色对应的权限点;新增角色 / 调整权限点归属须改代码走评审,本页不提供编辑入口。
      </Typography.Paragraph>
      {MODULE_ORDER.map((mod) => {
        const rows = [...permIndex.values()]
          .filter((r) => r.module === mod)
          .sort((a, b) => a.code.localeCompare(b.code));
        if (!rows.length) return null;
        return (
          <div key={mod} style={{ marginBottom: 32 }}>
            <Typography.Title level={5} style={{ marginBottom: 12 }}>
              {MODULE_LABEL[mod] ?? mod}
            </Typography.Title>
            <Table<PermissionRow>
              rowKey="code"
              size="small"
              columns={columns}
              dataSource={rows}
              pagination={false}
              scroll={{ x: 220 + roles.length * 150 }}
            />
          </div>
        );
      })}
    </Card>
  );
}
