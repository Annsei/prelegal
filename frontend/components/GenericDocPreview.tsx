"use client";

import { useEffect, useState } from "react";
import { marked } from "marked";
import { ApiError, templatesApi, type TemplateResponse } from "@/lib/api";
import type { Locale } from "@/lib/i18n";
import { useDictionary } from "@/lib/i18n";

type Props = {
  docId: string;
  fields: Record<string, string>;
  locale: Locale;
};

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; template: TemplateResponse }
  | { kind: "error"; message: string };

/**
 * Read-only preview for any catalog document other than MNDA.
 *
 * Fetches the markdown template from /api/templates/{docId}, prepends an
 * AI-collected "Cover Page Summary" listing the field_updates the chat has
 * extracted so far, and renders the standard terms via `marked`. The
 * underlying templates contain raw HTML spans (e.g. <span class="coverpage_link">)
 * which marked passes through; the styling is inherited from globals.css.
 *
 * MNDA still uses the dedicated MNDAPreview component for its bespoke
 * placeholder substitution and PDF layout — this component is only mounted
 * when the chat selects a non-MNDA document.
 */
export function GenericDocPreview({ docId, fields, locale }: Props) {
  const t = useDictionary(locale);
  const [load, setLoad] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    setLoad({ kind: "loading" });
    templatesApi
      .get(docId)
      .then((template) => {
        if (!cancelled) setLoad({ kind: "ready", template });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message =
          err instanceof ApiError && err.message
            ? err.message
            : t.templateUnavailable;
        setLoad({ kind: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, [docId, t.templateUnavailable]);

  if (load.kind === "loading") {
    return (
      <div
        className="rounded-lg border border-neutral-200 bg-white p-8 text-sm"
        style={{ color: "#888888" }}
      >
        …
      </div>
    );
  }
  if (load.kind === "error") {
    return (
      <div
        role="alert"
        className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
      >
        {load.message}
      </div>
    );
  }

  const { template } = load;
  // marked is sync when called without async-only extensions; the result is
  // typed as `string | Promise<string>` so we narrow.
  const standardTermsHtml = marked.parse(template.standard_terms, {
    async: false,
  }) as string;
  const fieldEntries = Object.entries(fields).filter(
    ([, value]) => value && value.trim() !== "",
  );

  return (
    <article
      data-print-root
      className="rounded-lg border border-neutral-200 bg-white p-8 leading-relaxed shadow-sm"
    >
      <header className="mb-6">
        <h1 className="text-2xl font-semibold" style={{ color: "#032147" }}>
          {template.title}
        </h1>
        <p className="mt-2 text-sm" style={{ color: "#888888" }}>
          {t.comingSoon}
        </p>
      </header>

      {fieldEntries.length > 0 && (
        <section
          className="mb-8 rounded-md border border-neutral-200 p-4"
          style={{ background: "#fef9e7" }}
        >
          <h2
            className="mb-3 text-sm font-semibold uppercase tracking-wide"
            style={{ color: "#032147" }}
          >
            Cover Page Summary
          </h2>
          <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-2 text-sm">
            {fieldEntries.map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="font-medium" style={{ color: "#032147" }}>
                  {key}
                </dt>
                <dd style={{ color: "#032147" }}>{value}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      <div
        className="prose prose-sm max-w-none"
        style={{ color: "#032147" }}
        dangerouslySetInnerHTML={{ __html: standardTermsHtml }}
      />
    </article>
  );
}
