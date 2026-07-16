// 报价语言选项(zh/en/sw 三选一)。前端唯一源头;值域权威在后端 core/languages.py
// SUPPORTED_QUOTE_LANGUAGES,此处为其 UI 镜像(报价编辑器与客户表单共用)。
export const QUOTE_LANGUAGE_OPTIONS = [
  { value: "zh", label: "中文" },
  { value: "en", label: "English" },
  { value: "sw", label: "Kiswahili" },
];

/** code → 展示 label(列表列用);未知值回显原 code 兜底。 */
export function quoteLanguageLabel(v: string | null | undefined): string {
  return QUOTE_LANGUAGE_OPTIONS.find((o) => o.value === v)?.label ?? v ?? "—";
}
