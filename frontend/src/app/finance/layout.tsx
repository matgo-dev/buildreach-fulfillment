import { ReactNode } from "react";

// 财务段是多子域(应付 / 应收),各子域权限门不同(payable:read / receivable:read),
// 故守卫下沉到各子路由 layout,本层仅透传;外壳由根 layout 的 ShellGate 统一提供。
export default function FinanceLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
