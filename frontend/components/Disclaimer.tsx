import type { Locale } from "@/lib/i18n";
import { useDictionary } from "@/lib/i18n";

type Props = {
  locale: Locale;
  // "banner" sits above the preview paper; "footer" runs along the bottom
  // of the page; "compact" is a single small line under the login form.
  variant: "banner" | "footer" | "compact";
};

/**
 * Legal-review disclaimer surfaced wherever a user might mistake the
 * generated document for a finished, lawyer-approved agreement.
 *
 * The banner stays visible without covering agreement text. Footer is muted
 * so it does not compete with the editor; compact is the smallest single-line
 * form for tight spaces.
 */
export function Disclaimer({ locale, variant }: Props) {
  const t = useDictionary(locale);
  if (variant === "banner") {
    return (
      <div role="note" className="no-print draft-notice">
        <span aria-hidden="true" className="draft-notice-icon">
          !
        </span>
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
