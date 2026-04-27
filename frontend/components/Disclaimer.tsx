import type { Locale } from "@/lib/i18n";
import { useDictionary } from "@/lib/i18n";

type Props = {
  locale: Locale;
  // "banner" sits above the preview; "footer" runs along the bottom of
  // the page; "compact" is a single small line e.g. under the login form.
  variant: "banner" | "footer" | "compact";
};

/**
 * Legal-review disclaimer surfaced wherever a user might mistake the
 * generated document for a finished, lawyer-approved agreement.
 *
 * Banner uses the accent yellow to draw the eye next to the preview;
 * footer is muted so it doesn't compete with the editor; compact is the
 * smallest single-line form for tight spaces (login page, modals).
 */
export function Disclaimer({ locale, variant }: Props) {
  const t = useDictionary(locale);
  if (variant === "banner") {
    return (
      <div
        role="note"
        className="no-print mb-3 rounded-md border border-yellow-300 px-3 py-2 text-xs"
        style={{ background: "#fef9e7", color: "#032147" }}
      >
        ⚠ {t.disclaimer}
      </div>
    );
  }
  if (variant === "footer") {
    return (
      <footer
        className="no-print border-t border-neutral-200 bg-white px-6 py-3 text-center text-xs"
        style={{ color: "#888888" }}
      >
        {t.disclaimer}
      </footer>
    );
  }
  return (
    <p className="text-xs" style={{ color: "#888888" }}>
      {t.disclaimerShort}
    </p>
  );
}
