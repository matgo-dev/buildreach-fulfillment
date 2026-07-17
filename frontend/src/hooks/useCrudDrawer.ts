"use client";
import { useState } from "react";
import { App } from "antd";
import type { FormInstance } from "antd";
import { resolveBizError } from "@/lib/errorMessages";

export type CrudDrawerMode = "view" | "create" | "edit" | null;

/**
 * 主数据 CRUD 抽屉状态机:mode/current/saving + openView/openCreate/openEdit/closeDrawer/onSubmit 骨架。
 * 页面差异留在页面层:view 态渲染内容、行级操作(停用/改角色/重置密码等)不进 hook。
 * - fetchDetail 省略 = openEdit 直接吃传入的行对象(用户管理页:列表行即完整数据,无详情接口)。
 * - fillForm 省略 = form.setFieldsValue(整个详情对象)。
 */
export function useCrudDrawer<TDetail extends { id: number }, TSave>({
  form,
  fetchDetail,
  fillForm,
  prepareCreate,
  create,
  update,
  afterSubmit,
  messages,
}: {
  form: FormInstance;
  /** 打开 view/edit 时按 id 拉详情;省略则 openEdit 必须直接传行对象、openView 不可用。 */
  fetchDetail?: (id: number) => Promise<TDetail>;
  /** 编辑态表单回显映射(默认整对象 setFieldsValue)。 */
  fillForm?: (detail: TDetail) => void;
  /** 新建打开后的表单预填(resetFields 之后执行)。 */
  prepareCreate?: () => void;
  create: (values: TSave) => Promise<unknown>;
  update: (current: TDetail, values: TSave) => Promise<unknown>;
  /** 提交成功且抽屉关闭后的刷新回调(通常 = 列表 load)。 */
  afterSubmit: () => void;
  messages: { created: string; saved: string; loadFailed: string };
}) {
  const { message } = App.useApp();
  const [mode, setMode] = useState<CrudDrawerMode>(null);
  const [current, setCurrent] = useState<TDetail | null>(null);
  const [saving, setSaving] = useState(false);

  async function openView(id: number) {
    if (!fetchDetail) return;
    setMode("view");
    setCurrent(null);
    try {
      setCurrent(await fetchDetail(id));
    } catch (e) {
      message.error(resolveBizError(e, messages.loadFailed));
      setMode(null);
    }
  }

  async function openEdit(target: number | TDetail) {
    try {
      const detail =
        typeof target === "number"
          ? await (fetchDetail as (id: number) => Promise<TDetail>)(target)
          : target;
      setCurrent(detail);
      if (fillForm) fillForm(detail);
      else form.setFieldsValue(detail);
      setMode("edit");
    } catch (e) {
      message.error(resolveBizError(e, messages.loadFailed));
    }
  }

  function openCreate() {
    setCurrent(null);
    form.resetFields();
    prepareCreate?.();
    setMode("create");
  }

  function closeDrawer() {
    setMode(null);
    setCurrent(null);
    form.resetFields();
  }

  async function onSubmit() {
    let values: TSave;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setSaving(true);
    try {
      if (mode === "create") {
        await create(values);
        message.success(messages.created);
      } else if (mode === "edit" && current) {
        await update(current, values);
        message.success(messages.saved);
      }
      closeDrawer();
      afterSubmit();
    } catch (e) {
      message.error(resolveBizError(e, "保存失败"));
    } finally {
      setSaving(false);
    }
  }

  return { mode, current, saving, openView, openCreate, openEdit, closeDrawer, onSubmit };
}
