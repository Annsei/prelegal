"use client";

import { useEffect, useState } from "react";
import { GenericDocPreview } from "@/components/GenericDocPreview";
import { LanguageToggle } from "@/components/LanguageToggle";
import { MNDAChat } from "@/components/MNDAChat";
import { MNDAForm } from "@/components/MNDAForm";
import { MNDAPreview } from "@/components/MNDAPreview";
import type { Locale } from "@/lib/i18n";
import { useDictionary } from "@/lib/i18n";
import { INITIAL_STATE, type MndaState } from "@/lib/mndaState";
import type { User } from "@/lib/api";
import { clearUser, readUser } from "@/lib/session";

type EditMode = "chat" | "form";

const MNDA_DOC_ID = "mutual-nda";

function lookupDocTitle(catalog: { id: string; title: string }[], id: string): string {
  const hit = catalog.find((d) => d.id === id);
  return hit?.title ?? id;
}

// Catalog is small and comes from the build-time CLAUDE.md import path.
// We hardcode the `id → title` pairs the UI needs rather than fetch them,
// since the catalog itself is already in the LLM prompt server-side.
const CATALOG_TITLES: { id: string; title: string }[] = [
  { id: "mutual-nda", title: "Mutual Non-Disclosure Agreement (MNDA)" },
  { id: "cloud-service-agreement", title: "Cloud Service Agreement (CSA)" },
  { id: "design-partner-agreement", title: "Design Partner Agreement" },
  { id: "service-level-agreement", title: "Service Level Agreement (SLA)" },
  { id: "professional-services-agreement", title: "Professional Services Agreement (PSA)" },
  { id: "data-processing-agreement", title: "Data Processing Agreement (DPA)" },
  { id: "software-license-agreement", title: "Software License Agreement" },
  { id: "partnership-agreement", title: "Partnership Agreement" },
  { id: "pilot-agreement", title: "Pilot Agreement" },
  { id: "business-associate-agreement", title: "Business Associate Agreement (BAA)" },
  { id: "ai-addendum", title: "AI Addendum" },
];

export default function Home() {
  const [locale, setLocale] = useState<Locale>("zh");
  const [state, setState] = useState<MndaState>(INITIAL_STATE);
  const [user, setUser] = useState<User | null>(null);
  const [mode, setMode] = useState<EditMode>("chat");
  // The chat starts in MNDA mode by default — that is the only doc with a
  // full form/preview/PDF flow. The LLM may switch this to any catalog id.
  const [docId, setDocId] = useState<string>(MNDA_DOC_ID);
  const [genericFields, setGenericFields] = useState<Record<string, string>>({});
  const t = useDictionary(locale);

  useEffect(() => {
    const stored = readUser();
    if (!stored) {
      window.location.replace("/login");
      return;
    }
    setUser(stored);
  }, []);

  if (!user) {
    // Don't render the platform until we've confirmed a session exists.
    // The effect above will redirect to /login if not.
    return null;
  }

  const isMnda = docId === MNDA_DOC_ID;
  const docTitle = lookupDocTitle(CATALOG_TITLES, docId);

  return (
    <div className="min-h-screen">
      <header className="no-print border-b border-neutral-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div>
            <h1 className="text-lg font-semibold text-neutral-900">
              {t.appTitle}
            </h1>
            <p className="text-sm text-neutral-600">{t.appSubtitle}</p>
            <p className="mt-1 text-xs" style={{ color: "#753991" }}>
              {t.drafting}: <span className="font-medium">{docTitle}</span>
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span
              className="hidden text-xs sm:inline"
              style={{ color: "#888888" }}
              title={user.email}
            >
              {user.email}
            </span>
            <button
              type="button"
              onClick={() => {
                clearUser();
                window.location.assign("/login");
              }}
              className="rounded-md border border-neutral-300 bg-white px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
            >
              Sign out
            </button>
            <LanguageToggle
              locale={locale}
              onToggle={() => setLocale(locale === "zh" ? "en" : "zh")}
            />
            <button
              type="button"
              onClick={() => window.print()}
              className="rounded-md bg-neutral-900 px-4 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-neutral-700"
              title={t.printHint}
            >
              {t.download}
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-7xl grid-cols-1 gap-6 px-6 py-6 lg:grid-cols-[minmax(320px,460px)_1fr]">
        <div className="no-print">
          <div role="tablist" className="mb-3 flex gap-2">
            <ModeTab
              active={mode === "chat"}
              onClick={() => setMode("chat")}
              label={t.chat.tab}
            />
            {/* The manual-edit form only knows MNDA fields today; hide it
                while the user is drafting any other document so we don't
                let them edit MNDA state behind a CSA preview. */}
            {isMnda && (
              <ModeTab
                active={mode === "form"}
                onClick={() => setMode("form")}
                label={t.chat.formTab}
              />
            )}
          </div>
          {mode === "chat" || !isMnda ? (
            <MNDAChat
              locale={locale}
              state={state}
              onStateChange={setState}
              onDocChange={setDocId}
              onFieldUpdates={(updates) =>
                setGenericFields((prev) => ({ ...prev, ...updates }))
              }
            />
          ) : (
            <div className="rounded-lg border border-neutral-200 bg-white p-5 shadow-sm">
              <MNDAForm locale={locale} value={state} onChange={setState} />
            </div>
          )}
          <p className="mt-3 text-xs text-neutral-500">{t.printHint}</p>
        </div>

        <div>
          {isMnda ? (
            <MNDAPreview value={state} />
          ) : (
            <GenericDocPreview
              docId={docId}
              fields={genericFields}
              locale={locale}
            />
          )}
        </div>
      </main>
    </div>
  );
}

function ModeTab({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className="rounded-md px-3 py-1.5 text-sm font-medium"
      style={{
        background: active ? "#209dd7" : "white",
        color: active ? "white" : "#032147",
        border: `1px solid ${active ? "#209dd7" : "#d4d4d4"}`,
      }}
    >
      {label}
    </button>
  );
}
