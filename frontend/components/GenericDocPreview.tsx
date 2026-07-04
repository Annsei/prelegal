"use client";

import { marked } from "marked";
import type { TemplateResponse } from "@/lib/api";
import type { Locale } from "@/lib/i18n";
import { useDictionary } from "@/lib/i18n";
import {
  annotateTermRefs,
  extraFields,
  localized,
  type DocManifest,
} from "@/lib/docManifest";
import type { TemplateLoad } from "@/lib/useDocTemplate";

type Props = {
  load: TemplateLoad;
  fields: Record<string, string>;
  locale: Locale;
};

/**
 * Preview pane for any catalog document other than MNDA. The template
 * (and its manifest) is fetched by the page via useDocTemplate — this
 * component only renders.
 *
 * Documents WITH a cover-page manifest get the real treatment: a
 * structured Cover Page whose values come from the chat/form, plus the
 * standard terms with every cover-page term reference highlighted as
 * defined (tooltip shows the value) or still missing. The body text is
 * NOT substituted inline — in Common Paper agreements the body refers to
 * cover-page terms by name, and the cover page is where values live.
 *
 * Documents WITHOUT a manifest fall back to the flat key/value summary
 * card over the raw template.
 */
export function GenericDocPreview({ load, fields, locale }: Props) {
  const t = useDictionary(locale);

  if (load.kind === "loading" || load.kind === "idle") {
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
  const manifest = template.manifest ?? null;
  const annotated = annotateTermRefs(
    template.standard_terms,
    manifest,
    fields,
  );
  // marked is sync when called without async-only extensions; the result is
  // typed as `string | Promise<string>` so we narrow.
  const standardTermsHtml = marked.parse(annotated, { async: false }) as string;

  return (
    <article
      data-print-root
      className="rounded-lg border border-neutral-200 bg-white p-8 leading-relaxed shadow-sm"
    >
      <header className="mb-6">
        <h1 className="text-2xl font-semibold" style={{ color: "#032147" }}>
          {template.title}
        </h1>
        <p className="no-print mt-2 text-sm" style={{ color: "#888888" }}>
          {manifest ? t.manifestNote : t.comingSoon}
        </p>
      </header>

      {manifest ? (
        <CoverPage
          manifest={manifest}
          fields={fields}
          locale={locale}
          template={template}
        />
      ) : (
        <SummaryCard fields={fields} />
      )}

      <div
        className="prose prose-sm max-w-none"
        style={{ color: "#032147" }}
        dangerouslySetInnerHTML={{ __html: standardTermsHtml }}
      />
    </article>
  );
}

function CoverPage({
  manifest,
  fields,
  locale,
  template,
}: {
  manifest: DocManifest;
  fields: Record<string, string>;
  locale: Locale;
  template: TemplateResponse;
}) {
  const t = useDictionary(locale);
  const extras = extraFields(manifest, fields);

  return (
    <section
      aria-label={t.coverPage.title}
      className="mb-8 rounded-md border border-neutral-300 p-5"
      style={{ background: "#fbfaf7" }}
    >
      <h2
        className="mb-1 text-lg font-semibold"
        style={{ color: "#032147" }}
      >
        {t.coverPage.title}
      </h2>
      <p className="mb-4 text-xs" style={{ color: "#888888" }}>
        {template.title}
      </p>

      {manifest.sections.map((section) => {
        const sectionFields = manifest.fields.filter(
          (field) => field.section === section.key,
        );
        if (sectionFields.length === 0) return null;
        return (
          <div key={section.key} className="mb-4 last:mb-0">
            <h3
              className="mb-2 text-xs font-semibold uppercase tracking-wide"
              style={{ color: "#753991" }}
            >
              {localized(section.label, locale)}
            </h3>
            <dl className="grid grid-cols-[minmax(10rem,max-content)_1fr] gap-x-4 gap-y-1.5 text-sm">
              {sectionFields.map((field) => {
                const value = (fields[field.key] ?? "").trim();
                return (
                  <div key={field.key} className="contents">
                    <dt className="font-medium" style={{ color: "#032147" }}>
                      {localized(field.label, locale)}
                    </dt>
                    <dd style={{ color: "#032147" }}>
                      {value ? (
                        <span className="filled">{value}</span>
                      ) : field.required ? (
                        <span className="missing">{t.coverPage.missing}</span>
                      ) : (
                        <span style={{ color: "#888888" }}>—</span>
                      )}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </div>
        );
      })}

      {extras.length > 0 && (
        <div className="mt-4 border-t border-neutral-200 pt-3">
          <h3
            className="mb-2 text-xs font-semibold uppercase tracking-wide"
            style={{ color: "#753991" }}
          >
            {t.coverPage.otherTerms}
          </h3>
          <dl className="grid grid-cols-[minmax(10rem,max-content)_1fr] gap-x-4 gap-y-1.5 text-sm">
            {extras.map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="font-medium" style={{ color: "#032147" }}>
                  {key}
                </dt>
                <dd style={{ color: "#032147" }}>{value}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </section>
  );
}

/** Pre-manifest fallback: flat list of whatever the chat collected. */
function SummaryCard({ fields }: { fields: Record<string, string> }) {
  const entries = Object.entries(fields).filter(
    ([, value]) => value && value.trim() !== "",
  );
  if (entries.length === 0) return null;
  return (
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
        {entries.map(([key, value]) => (
          <div key={key} className="contents">
            <dt className="font-medium" style={{ color: "#032147" }}>
              {key}
            </dt>
            <dd style={{ color: "#032147" }}>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
