import { RouteGuard } from "@/components/auth/RouteGuard";
import { Permissions } from "@/config/permission-matrix";
import type { ReactNode } from "react";

export default function ReverseRequestsLayout({ children }: { children: ReactNode }) {
  return <RouteGuard requiredPermissions={[Permissions.REVERSE_READ]}>{children}</RouteGuard>;
}
