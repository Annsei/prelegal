"use client";

import type { DocumentSummary } from "@/lib/api";
import type { Locale } from "@/lib/i18n";
import { useDictionary } from "@/lib/i18n";

type Props = {
  locale: Locale;
  documents: DocumentSummary[];
  activeId: number | null;
  catalogTitleFor: (docId: string) => string;
  onSelect: (id: number) => void;
  onCreate: () => void;
};

function relativeTime(iso: string, locale: Locale): string {
  const stamp = Date.parse(iso);
  if (!Number.isFinite(stamp)) return "";
  const deltaSec = Math.round((stamp - Date.now()) / 1000);
  const abs = Math.abs(deltaSec);
  const rtf = new Intl.RelativeTimeFormat(locale === "zh" ? "zh-CN" : "en", {
    numeric: "auto",
  });
  if (abs < 60) return rtf.format(Math.round(deltaSec / 1), "second");
  if (abs < 3600) return rtf.format(Math.round(deltaSec / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(deltaSec / 3600), "hour");
  if (abs < 86400 * 30) return rtf.format(Math.round(deltaSec / 86400), "day");
  return rtf.format(Math.round(deltaSec / (86400 * 30)), "month");
}

export function DocumentSidebar({
  locale,
  documents,
  activeId,
  catalogTitleFor,
  onSelect,
  onCreate,
}: Props) {
  const t = useDictionary(locale);
  return (
    <aside className="sidebar-panel no-print flex flex-col">
      <button
        type="button"
        onClick={onCreate}
        className="btn btn-primary w-full"
      >
        {t.sidebar.newDraft}
      </button>
      <div className="mt-5 flex items-center gap-2 px-1 pb-2">
        <h2
          className="text-xs font-semibold uppercase tracking-[0.14em]"
          style={{ color: "var(--ink-3)" }}
        >
          {t.sidebar.title}
        </h2>
        <div className="h-px flex-1" style={{ background: "var(--rule-soft)" }} />
      </div>
      <ul className="-mx-1 flex-1 space-y-1 overflow-y-auto px-1 pb-2">
        {documents.length === 0 ? (
          <li className="sidebar-empty px-3 py-5 text-xs leading-relaxed">
            {t.sidebar.empty}
          </li>
        ) : (
          documents.map((doc) => {
            const isActive = doc.id === activeId;
            const when = relativeTime(doc.updated_at, locale);
            const catalogTitle = catalogTitleFor(doc.doc_id);
            return (
              <li key={doc.id}>
                <button
                  type="button"
                  onClick={() => onSelect(doc.id)}
                  className="file-item text-sm"
                  data-active={isActive}
                  style={{ color: "var(--ink)" }}
                >
                  <div className="truncate font-medium">
                    {doc.title.trim() || t.sidebar.untitled}
                  </div>
                  <div
                    className="truncate text-xs"
                    style={{ color: "var(--ink-3)" }}
                  >
                    {when ? `${catalogTitle} · ${when}` : catalogTitle}
                  </div>
                </button>
              </li>
            );
          })
        )}
      </ul>
    </aside>
  );
}
