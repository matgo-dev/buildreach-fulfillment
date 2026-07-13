/** 读 i18n JSONB:目标语言 → en → zh 兜底;全空返回空串。 */
export function display(i18n: Record<string, string> | undefined | null, lang = "zh"): string {
  if (!i18n) return "";
  return i18n[lang] || i18n.en || i18n.zh || "";
}
