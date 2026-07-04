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
    <button type="button" onClick={onToggle} className="btn btn-ghost">
      {t.langToggle}
    </button>
  );
}
