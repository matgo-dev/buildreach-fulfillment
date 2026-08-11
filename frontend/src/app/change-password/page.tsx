"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { authApi } from "@/lib/auth";
import { ApiError } from "@/lib/api";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { useAuthStore } from "@/stores/authStore";

function ChangePasswordContent() {
  const router = useRouter();
  const { setAccessToken, setUser } = useAuthStore();
  const user = useAuthStore((s) => s.user);
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (newPassword !== confirmPassword) {
      setError("两次输入的新密码不一致");
      return;
    }
    setSubmitting(true);
    try {
      const tokens = await authApi.changePassword(oldPassword, newPassword);
      setAccessToken(tokens.access_token);
      const me = await authApi.me();
      setUser(me);
      router.replace("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "修改密码失败,请重试");
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
        <h1 className="text-lg font-semibold text-brand">
          {user?.must_change_password ? "首次登录,请修改密码" : "修改密码"}
        </h1>
        <p className="mt-1 text-sm text-slate-500">密码须 6-20 位,仅限字母和数字</p>

        <label className="mt-6 block text-sm text-slate-700">
          原密码
          <input
            type="password"
            value={oldPassword}
            onChange={(e) => setOldPassword(e.target.value)}
            required
            autoFocus
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand"
          />
        </label>

        <label className="mt-4 block text-sm text-slate-700">
          新密码
          <input
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            required
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand"
          />
        </label>

        <label className="mt-4 block text-sm text-slate-700">
          确认新密码
          <input
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
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
          {submitting ? "提交中…" : "确认修改"}
        </button>
      </form>
    </main>
  );
}

export default function ChangePasswordPage() {
  return (
    <RouteGuard enforceChangePassword={false}>
      <ChangePasswordContent />
    </RouteGuard>
  );
}
