import type { Locale } from "@/lib/i18n";
import { useDictionary } from "@/lib/i18n";

export type SaveState = "idle" | "saving" | "saved" | "failed";

type Props = {
  locale: Locale;
  state: SaveState;
};

/** Minimal indicator next to the document title, mirrors Notion/Linear-style
 *  "Saved" badge so the user has confidence the auto-save fired. */
export function SaveStatus({ locale, state }: Props) {
  const t = useDictionary(locale);
  if (state === "idle") return null;
  const label =
    state === "saving"
      ? t.saveStatus.saving
      : state === "failed"
        ? t.saveStatus.failed
        : t.saveStatus.saved;
  const color =
    state === "failed" ? "#b91c1c" : state === "saving" ? "#7e8a9b" : "#2f7d4f";
  return (
    <span
      className="inline-flex items-center gap-1.5 text-xs"
      style={{ color }}
      role="status"
      aria-live="polite"
    >
      <span className="save-dot" data-state={state} aria-hidden />
      {label}
    </span>
  );
}
