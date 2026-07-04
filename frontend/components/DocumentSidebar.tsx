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
    <aside className="no-print flex h-[calc(100vh-9.5rem)] flex-col">
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
          <li
            className="px-2 py-3 text-xs leading-relaxed"
            style={{ color: "var(--ink-3)" }}
          >
            {t.sidebar.empty}
          </li>
        ) : (
          documents.map((doc) => {
            const isActive = doc.id === activeId;
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
                    {catalogTitleFor(doc.doc_id)}
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
