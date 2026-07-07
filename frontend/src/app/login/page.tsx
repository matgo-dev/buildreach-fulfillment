"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { authApi } from "@/lib/auth";
import { ApiError } from "@/lib/api";
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
      router.replace(me.must_change_password ? "/change-password" : "/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "登录失败,请重试");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-6">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-8 shadow-sm"
      >
        <h1 className="text-lg font-semibold text-brand">登录</h1>
        <p className="mt-1 text-sm text-slate-500">履约系统</p>

        <label className="mt-6 block text-sm text-slate-700">
          邮箱 / 用户名
          <input
            type="text"
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            required
            autoFocus
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand"
          />
        </label>

        <label className="mt-4 block text-sm text-slate-700">
          密码
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand"
          />
        </label>

        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

        <button
          type="submit"
          disabled={submitting}
          className="mt-6 w-full rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-dark disabled:opacity-60"
        >
          {submitting ? "登录中…" : "登录"}
        </button>
      </form>
    </main>
  );
}
