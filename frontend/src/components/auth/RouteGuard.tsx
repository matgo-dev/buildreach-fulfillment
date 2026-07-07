"use client";
import { ReactNode, useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";

import { useAuthStore } from "@/stores/authStore";
import type { RoleCode } from "@/lib/auth";
import type { PermissionCode } from "@/config/permission-matrix";

interface Props {
  /** 允许的角色(任一即可)。不传则只要登录即可。 */
  allowRoles?: RoleCode[];
  /** 要求拥有的权限点(全部都要)。 */
  requiredPermissions?: PermissionCode[];
  /** must_change_password=true 时是否强制跳改密。默认 true。 */
  enforceChangePassword?: boolean;
  children: ReactNode;
}

/**
 * 路由守卫。顺序:loaded → 未登录 → 强制改密 → 角色限制 → 权限点限制 → 通过
 *
 * UX 层防护,后端 require_permission 才是安全底线。
 */
export function RouteGuard({
  allowRoles,
  requiredPermissions,
  enforceChangePassword = true,
  children,
}: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const { user, loaded } = useAuthStore();

  const missingPerm =
    user && requiredPermissions && requiredPermissions.length > 0
      ? requiredPermissions.find((p) => !user.permissions.includes(p))
      : undefined;

  useEffect(() => {
    if (!loaded) return;
    if (!user) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
      return;
    }
    if (enforceChangePassword && user.must_change_password && pathname !== "/change-password") {
      router.replace("/change-password");
      return;
    }
    if (allowRoles && !allowRoles.some((r) => user.roles.includes(r))) {
      router.replace("/login");
      return;
    }
    if (missingPerm) {
      router.replace("/login");
    }
  }, [user, loaded, allowRoles, missingPerm, enforceChangePassword, pathname, router]);

  if (!loaded) return null;
  if (!user) return null;
  if (enforceChangePassword && user.must_change_password && pathname !== "/change-password") return null;
  if (allowRoles && !allowRoles.some((r) => user.roles.includes(r))) return null;
  if (missingPerm) return null;

  return <>{children}</>;
}
