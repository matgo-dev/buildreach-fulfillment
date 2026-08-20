import type { ReactNode } from "react";
import {
  AccountBookOutlined,
  ApartmentOutlined,
  AppstoreOutlined,
  CompassOutlined,
  ContainerOutlined,
  CreditCardOutlined,
  DatabaseOutlined,
  ExportOutlined,
  FileTextOutlined,
  InboxOutlined,
  KeyOutlined,
  PayCircleOutlined,
  ProfileOutlined,
  ReconciliationOutlined,
  SafetyCertificateOutlined,
  ShopOutlined,
  ShoppingCartOutlined,
  TeamOutlined,
  VerticalAlignBottomOutlined,
} from "@ant-design/icons";

import { Permissions, type PermissionCode } from "@/config/permission-matrix";

export interface MenuItemConfig {
  key: string;
  icon: ReactNode;
  label: string;
  perm: PermissionCode | null;
}

export interface MenuGroupConfig {
  group: string;
  items: MenuItemConfig[];
}

// 菜单按 ERP 职能域分 6 组(DESIGN §6):仅呈现层分组,路由与 perm 门控逻辑不变。
// 菜单项按权限显隐(perm=可见所需权限点),避免死链;后端 RouteGuard 仍是访问底线。
export const MENU_GROUPS: MenuGroupConfig[] = [
  {
    group: "帮助",
    items: [
      { key: "/guide", icon: <CompassOutlined />, label: "平台导览", perm: null },
    ],
  },
  {
    group: "基础资料",
    items: [
      { key: "/catalog/spus", icon: <AppstoreOutlined />, label: "商品目录", perm: Permissions.PRODUCT_READ },
      { key: "/catalog/categories", icon: <ApartmentOutlined />, label: "商品分类", perm: Permissions.PRODUCT_READ },
      { key: "/sales/customers", icon: <TeamOutlined />, label: "客户", perm: Permissions.CUSTOMER_READ },
      { key: "/purchasing/suppliers", icon: <ShopOutlined />, label: "供应商", perm: Permissions.SUPPLIER_READ },
    ],
  },
  {
    group: "销售",
    items: [
      { key: "/sales/quotations", icon: <FileTextOutlined />, label: "报价管理", perm: Permissions.QUOTE_MANAGE },
      { key: "/sales/orders", icon: <ProfileOutlined />, label: "销售单", perm: Permissions.SALES_READ },
    ],
  },
  {
    group: "采购",
    items: [
      { key: "/purchasing/orders", icon: <ShoppingCartOutlined />, label: "采购单", perm: Permissions.PURCHASE_READ },
    ],
  },
  {
    group: "仓储物流",
    items: [
      { key: "/inbound", icon: <InboxOutlined />, label: "入库单", perm: Permissions.INBOUND_READ },
      { key: "/inventory", icon: <DatabaseOutlined />, label: "库存", perm: Permissions.INVENTORY_READ },
      { key: "/shipments", icon: <ContainerOutlined />, label: "发运柜", perm: Permissions.SHIPMENT_READ },
      { key: "/outbound", icon: <ExportOutlined />, label: "出库单", perm: Permissions.OUTBOUND_READ },
    ],
  },
  {
    group: "财务",
    items: [
      { key: "/finance/receivables", icon: <AccountBookOutlined />, label: "应收款", perm: Permissions.RECEIVABLE_READ },
      { key: "/finance/customer-credits", icon: <CreditCardOutlined />, label: "客户余额贷项", perm: Permissions.RECEIVABLE_READ },
      { key: "/finance/receipts", icon: <VerticalAlignBottomOutlined />, label: "收款单", perm: Permissions.RECEIPT_READ },
      { key: "/finance/payables", icon: <ReconciliationOutlined />, label: "应付款", perm: Permissions.PAYABLE_READ },
      { key: "/finance/payments", icon: <PayCircleOutlined />, label: "付款单", perm: Permissions.PAYMENT_READ },
    ],
  },
  {
    group: "系统",
    items: [
      { key: "/admin/users", icon: <SafetyCertificateOutlined />, label: "用户管理", perm: Permissions.USER_MANAGE },
      { key: "/admin/roles", icon: <KeyOutlined />, label: "角色权限", perm: Permissions.ROLE_MANAGE },
    ],
  },
];

export function getVisibleMenuGroups(hasPermission: (perm: PermissionCode) => boolean): MenuGroupConfig[] {
  return MENU_GROUPS.map((g) => ({
    ...g,
    items: g.items.filter((m) => m.perm === null || hasPermission(m.perm)),
  })).filter((g) => g.items.length > 0);
}

export function getDefaultPathForPermissions(permissions: string[]): string {
  const permissionSet = new Set(permissions);
  const firstPermittedItem = MENU_GROUPS.flatMap((g) => g.items)
    .find((m) => m.perm !== null && permissionSet.has(m.perm));
  return firstPermittedItem?.key ?? "/guide";
}
