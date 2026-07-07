"use client";

import { RouteGuard } from "@/components/auth/RouteGuard";
import { authApi } from "@/lib/auth";
import { useAuthStore } from "@/stores/authStore";
import { useRouter } from "next/navigation";

function HomeContent() {
  const router = useRouter();
  const { user, clear } = useAuthStore();

  if (!user) return null;

  async function handleLogout() {
    try {
      await authApi.logout();
    } catch {
      /* 登出失败也清本地态,不阻塞用户 */
    }
    clear();
    router.replace("/login");
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col items-center justify-center gap-6 px-6 text-center">
      <div className="rounded-2xl border border-slate-200 bg-white px-10 py-8 shadow-sm">
        <h1 className="text-xl font-semibold text-brand">M0 地基就绪</h1>
        <p className="mt-4 text-sm text-slate-600">
          已登录:<span className="font-medium text-slate-900">{user.name}</span>{" "}
          (<span className="text-slate-500">{user.email}</span>)
        </p>
        <p className="mt-1 text-xs text-slate-400">角色:{user.roles.join(", ")}</p>
        <button
          onClick={handleLogout}
          className="mt-6 rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
        >
          登出
        </button>
      </div>
    </main>
  );
}

export default function HomePage() {
  return (
    <RouteGuard>
      <HomeContent />
    </RouteGuard>
  );
}
