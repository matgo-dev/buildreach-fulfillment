import { ReactNode } from "react";

// 财务段是多子域(应付 / 应收),各子域权限门不同(payable:read / receivable:read),
// 故守卫 + AppShell 外壳下沉到各子路由 layout,本层仅透传。
export default function FinanceLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
