"use client";

import { useEffect, useState } from "react";
import { LanguageToggle } from "@/components/LanguageToggle";
import { MNDAForm } from "@/components/MNDAForm";
import { MNDAPreview } from "@/components/MNDAPreview";
import type { Locale } from "@/lib/i18n";
import { useDictionary } from "@/lib/i18n";
import { INITIAL_STATE, type MndaState } from "@/lib/mndaState";
import type { User } from "@/lib/api";
import { clearUser, readUser } from "@/lib/session";

export default function Home() {
  const [locale, setLocale] = useState<Locale>("zh");
  const [state, setState] = useState<MndaState>(INITIAL_STATE);
  const [user, setUser] = useState<User | null>(null);
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

  return (
    <div className="min-h-screen">
      <header className="no-print border-b border-neutral-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div>
            <h1 className="text-lg font-semibold text-neutral-900">
              {t.appTitle}
            </h1>
            <p className="text-sm text-neutral-600">{t.appSubtitle}</p>
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

      <main className="mx-auto grid max-w-7xl grid-cols-1 gap-6 px-6 py-6 lg:grid-cols-[minmax(320px,420px)_1fr]">
        <div className="no-print">
          <div className="rounded-lg border border-neutral-200 bg-white p-5 shadow-sm">
            <MNDAForm locale={locale} value={state} onChange={setState} />
          </div>
          <p className="mt-3 text-xs text-neutral-500">{t.printHint}</p>
        </div>

        <div>
          <MNDAPreview value={state} />
        </div>
      </main>
    </div>
  );
}
