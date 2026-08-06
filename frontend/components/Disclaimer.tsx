import type { Locale } from "@/lib/i18n";
import { useDictionary } from "@/lib/i18n";

type Props = {
  locale: Locale;
  // "banner" sits above the preview paper; "footer" runs along the bottom of
  // the page; "compact" is a single small line e.g. under the login form.
  variant: "banner" | "footer" | "compact";
};

/**
 * Legal-review disclaimer surfaced wherever a user might mistake the
 * generated document for a finished, lawyer-approved agreement.
 *
 * Banner is a slim one-line notice outside the document paper; footer is
 * muted so it doesn't compete with the editor; compact is the smallest
 * single-line form for tight spaces (login page, modals).
 */
export function Disclaimer({ locale, variant }: Props) {
  const t = useDictionary(locale);
  if (variant === "banner") {
    return (
      <div role="note" className="no-print preview-disclaimer">
        <span aria-hidden="true">⚠</span>
        <span>{t.disclaimerShort}</span>
      </div>
    );
  }
  if (variant === "footer") {
    return (
      <footer
        className="no-print border-t px-6 py-3 text-center text-xs"
        style={{ borderColor: "var(--rule-soft)", color: "var(--ink-3)" }}
      >
        {t.disclaimer}
      </footer>
    );
  }
  return (
    <p className="text-xs" style={{ color: "var(--ink-3)" }}>
      {t.disclaimerShort}
    </p>
  );
}
