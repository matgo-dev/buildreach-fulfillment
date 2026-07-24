// iconKey → antd 图标。与 AppShell 同名菜单项 import 同一个组件(同源,非副本)。
import type { ReactNode } from "react";
import {
  AppstoreOutlined, TeamOutlined, ShopOutlined, FileTextOutlined, ProfileOutlined,
  ShoppingCartOutlined, InboxOutlined, DatabaseOutlined, ExportOutlined,
  ContainerOutlined, SendOutlined, AccountBookOutlined, CompassOutlined, AuditOutlined,
} from "@ant-design/icons";
import type { GuideIconKey } from "@/config/guideFlow";

export const GUIDE_ICONS: Record<GuideIconKey, ReactNode> = {
  product: <AppstoreOutlined />,
  customer: <TeamOutlined />,
  supplier: <ShopOutlined />,
  quotation: <FileTextOutlined />,
  salesOrder: <ProfileOutlined />,
  purchaseOrder: <ShoppingCartOutlined />,
  inbound: <InboxOutlined />,
  inventory: <DatabaseOutlined />,
  outbound: <ExportOutlined />,
  shipmentOpen: <ContainerOutlined />,
  shipment: <SendOutlined />,
  logistics: <CompassOutlined />,
  customs: <AuditOutlined />,
  receivable: <AccountBookOutlined />,
  receipt: <AccountBookOutlined />,
  payable: <AccountBookOutlined />,
  payment: <AccountBookOutlined />,
};
