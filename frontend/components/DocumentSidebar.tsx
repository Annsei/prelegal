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
    <aside className="no-print flex h-[calc(100vh-9rem)] flex-col rounded-lg border border-neutral-200 bg-white shadow-sm">
      <div className="border-b border-neutral-200 p-3">
        <button
          type="button"
          onClick={onCreate}
          className="w-full rounded-md px-3 py-2 text-sm font-medium text-white shadow-sm hover:opacity-90"
          style={{ backgroundColor: "#753991" }}
        >
          {t.sidebar.newDraft}
        </button>
      </div>
      <div className="px-3 pb-2 pt-3">
        <h2
          className="text-xs font-semibold uppercase tracking-wide"
          style={{ color: "#888888" }}
        >
          {t.sidebar.title}
        </h2>
      </div>
      <ul className="flex-1 overflow-y-auto px-2 pb-2">
        {documents.length === 0 ? (
          <li className="px-2 py-3 text-xs" style={{ color: "#888888" }}>
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
                  className="block w-full rounded-md px-3 py-2 text-left text-sm transition-colors"
                  style={{
                    // Faint tint of the Blue Primary token so we don't
                    // introduce a fourth blue value to the palette.
                    background: isActive
                      ? "rgba(32, 157, 215, 0.10)"
                      : "transparent",
                    color: "#032147",
                    border: `1px solid ${isActive ? "#209dd7" : "transparent"}`,
                  }}
                >
                  <div className="truncate font-medium">
                    {doc.title.trim() || t.sidebar.untitled}
                  </div>
                  <div
                    className="truncate text-xs"
                    style={{ color: "#888888" }}
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
