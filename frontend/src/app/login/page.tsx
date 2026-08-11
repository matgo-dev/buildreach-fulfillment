"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { authApi } from "@/lib/auth";
import { ApiError } from "@/lib/api";
import { getDefaultPathForPermissions } from "@/config/navigation";
import { useAuthStore } from "@/stores/authStore";

export default function LoginPage() {
  const router = useRouter();
  const { setAccessToken, setUser, setLoaded } = useAuthStore();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const tokens = await authApi.login(identifier, password);
      setAccessToken(tokens.access_token);
      const me = await authApi.me();
      setUser(me);
      setLoaded(true);
      router.replace(me.must_change_password ? "/change-password" : getDefaultPathForPermissions(me.permissions));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "登录失败,请重试");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    // 页面背景 DESIGN §1.2 bg;桌面优先、居中单卡片(克制,无营销 hero)。
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-6">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-8 shadow-lg"
      >
        {/* 品牌头:brand 方块 logo + 品名(DESIGN §2 大标题 text-xl font-black) */}
        <div className="flex flex-col items-center text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-brand text-xl font-black text-white">
            履
          </div>
          <h1 className="mt-3 text-xl font-black text-slate-900">履约系统</h1>
          <p className="mt-1 text-sm text-slate-500">供应链履约平台 · 内部运营</p>
        </div>

        <div className="mt-8 space-y-4">
          <label className="block">
            <span className="text-sm text-slate-600">邮箱 / 用户名</span>
            <input
              type="text"
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              required
              autoFocus
              className="mt-1 h-10 w-full rounded-md border border-slate-300 px-3 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/30"
            />
          </label>

          <label className="block">
            <span className="text-sm text-slate-600">密码</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="mt-1 h-10 w-full rounded-md border border-slate-300 px-3 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/30"
            />
          </label>
        </div>

        {/* 错误:DESIGN §1.3 danger(red-50 底 + red-700 文),不只裸红字 */}
        {error && (
          <div className="mt-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="mt-6 h-10 w-full rounded-md bg-brand text-sm font-medium text-white transition-colors hover:bg-brand-dark disabled:opacity-60"
        >
          {submitting ? "登录中…" : "登录"}
        </button>
      </form>
    </main>
  );
}
