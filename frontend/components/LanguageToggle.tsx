"use client";

import type { Locale } from "@/lib/i18n";
import { useDictionary } from "@/lib/i18n";

type Props = {
  locale: Locale;
  onToggle: () => void;
};

export function LanguageToggle({ locale, onToggle }: Props) {
  const t = useDictionary(locale);
  return (
    <button
      type="button"
      onClick={onToggle}
      className="rounded-md border border-neutral-300 bg-white px-3 py-1.5 text-sm text-neutral-700 shadow-sm hover:bg-neutral-50"
    >
      {t.langToggle}
    </button>
  );
}
