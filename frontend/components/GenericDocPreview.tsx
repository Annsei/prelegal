"use client";

import { marked } from "marked";
import {
  applyConditionalBlocks,
  ConditionalTemplateError,
} from "@/lib/conditionalBlocks";
import type { Locale } from "@/lib/i18n";
import { useDictionary } from "@/lib/i18n";
import {
  annotateTermRefs,
  extraFields,
  localized,
  type DocManifest,
} from "@/lib/docManifest";
import {
  stableFieldValues,
  type DraftFieldState,
  type DraftStateSnapshot,
} from "@/lib/draftState";
import type { TemplateLoad } from "@/lib/useDocTemplate";

type Props = {
  load: TemplateLoad;
  fields: Record<string, string>;
  draftState?: DraftStateSnapshot | null;
  locale: Locale;
};

/**
 * Preview pane for any catalog document. The template (and its manifest) is
 * fetched by the page via useDocTemplate — this component only renders.
 *
 * Documents WITH a cover-page manifest get the real treatment: a
 * structured Cover Page whose values come from the chat/form, plus the
 * standard terms with every cover-page term reference highlighted as
 * defined (tooltip shows the value) or still missing. The body text is
 * NOT substituted inline: the legal text references cover-page terms by
 * name, and the cover page is where values live.
 *
 * Documents WITHOUT a manifest fall back to the flat key/value summary
 * card over the raw template.
 */
export function GenericDocPreview({
  load,
  fields,
  draftState = null,
  locale,
}: Props) {
  const t = useDictionary(locale);

  if (load.kind === "loading" || load.kind === "idle") {
    return (
      <div className="card p-8 text-sm" style={{ color: "var(--ink-3)" }}>
        <span className="typing-dots" aria-hidden>
          <i />
          <i />
          <i />
        </span>
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
  const stableFields = manifest
    ? stableFieldValues(manifest, draftState, fields)
    : fields;
  let conditionalTerms: string;
  let conditionalCoverPage: string;
  try {
    conditionalTerms = manifest
      ? applyConditionalBlocks(template.standard_terms, manifest, stableFields)
      : template.standard_terms;
    conditionalCoverPage =
      manifest && template.cover_page
        ? applyConditionalBlocks(template.cover_page, manifest, stableFields)
        : template.cover_page ?? "";
  } catch (error) {
    if (!(error instanceof ConditionalTemplateError)) throw error;
    return (
      <div
        role="alert"
        className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
      >
        {t.templateUnavailable}
      </div>
    );
  }
  const annotated = annotateTermRefs(
    conditionalTerms,
    manifest,
    stableFields,
    draftState?.fields,
  );
  const annotatedCoverPage = conditionalCoverPage
    ? annotateTermRefs(
        conditionalCoverPage,
        manifest,
        stableFields,
        draftState?.fields,
      )
    : "";
  // marked is sync when called without async-only extensions; the result is
  // typed as `string | Promise<string>` so we narrow.
  const standardTermsHtml = marked.parse(annotated, { async: false }) as string;
  const coverPageHtml = annotatedCoverPage
    ? (marked.parse(annotatedCoverPage, { async: false }) as string)
    : "";

  return (
    <article
      data-print-root
      className="document-paper leading-relaxed"
    >
      <header className="document-header">
        <h1 className="display text-2xl">
          {template.title}
        </h1>
        {!manifest && (
          <p className="no-print mt-2 text-sm" style={{ color: "var(--ink-3)" }}>
            {t.comingSoon}
          </p>
        )}
      </header>

      {manifest ? (
        <CoverPage
          manifest={manifest}
          fields={fields}
          draftState={draftState}
          locale={locale}
        />
      ) : (
        <SummaryCard fields={fields} />
      )}

      {coverPageHtml && (
        <div
          className="document-prose document-cover-markdown mb-8"
          dangerouslySetInnerHTML={{ __html: coverPageHtml }}
        />
      )}

      <div
        className="document-prose"
        dangerouslySetInnerHTML={{ __html: standardTermsHtml }}
      />
    </article>
  );
}

function CoverPage({
  manifest,
  fields,
  draftState,
  locale,
}: {
  manifest: DocManifest;
  fields: Record<string, string>;
  draftState: DraftStateSnapshot | null;
  locale: Locale;
}) {
  const t = useDictionary(locale);
  const extras = extraFields(manifest, fields);

  return (
    <section
      aria-label={t.coverPage.title}
      className="cover-page-sheet mb-8"
    >
      <h2 className="display mb-4 text-xl">
        {t.coverPage.title}
      </h2>

      {manifest.sections.map((section) => {
        const sectionFields = manifest.fields.filter(
          (field) => field.section === section.key,
        );
        if (sectionFields.length === 0) return null;
        return (
          <div key={section.key} className="cover-page-section">
            <h3
              className="cover-page-section-title"
            >
              {localized(section.label, locale)}
            </h3>
            <dl className="cover-page-grid">
              {sectionFields.map((field) => {
                const fieldState = draftState?.fields[field.key];
                const value = displayValue(fieldState, fields[field.key]);
                return (
                  <div key={field.key} className="contents">
                    <dt>
                      {localized(field.label, locale)}
                    </dt>
                    <dd>
                      <CoverPageValue
                        value={value}
                        required={field.required}
                        fieldState={fieldState}
                        missingLabel={t.coverPage.missing}
                        labels={t.docForm}
                      />
                    </dd>
                  </div>
                );
              })}
            </dl>
          </div>
        );
      })}

      {extras.length > 0 && (
        <div className="cover-page-section mt-4">
          <h3
            className="cover-page-section-title"
          >
            {t.coverPage.otherTerms}
          </h3>
          <dl className="cover-page-grid">
            {extras.map(([key, value]) => (
              <div key={key} className="contents">
                <dt>{key}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </section>
  );
}

function displayValue(
  fieldState: DraftFieldState | undefined,
  fallback: string | undefined,
): string {
  if (fieldState?.value) return fieldState.value.trim();
  return (fallback ?? "").trim();
}

function CoverPageValue({
  value,
  required,
  fieldState,
  missingLabel,
  labels,
}: {
  value: string;
  required: boolean;
  fieldState?: DraftFieldState;
  missingLabel: string;
  labels: {
    pending: string;
    confirmed: string;
    conflict: string;
    current: string;
    candidate: string;
  };
}) {
  if (fieldState?.status === "conflict" && fieldState.conflict) {
    return (
      <span className="field-value space-y-0.5" data-state="conflict">
        <span className="block text-xs font-semibold">
          {labels.conflict}
        </span>
        <span className="block">
          {labels.current}: {fieldState.conflict.base_value ?? value}
        </span>
        <span className="block" style={{ color: "var(--ink-3)" }}>
          {labels.candidate}: {fieldState.conflict.proposed_value}
        </span>
      </span>
    );
  }
  if (value) {
    const state = fieldState?.status ?? "confirmed";
    return (
      <span className="field-value" data-state={state}>
        {value}
        {fieldState?.status === "pending_confirmation" && (
          <span className="value-chip" data-kind="pending">
            {labels.pending}
          </span>
        )}
        {fieldState?.status === "confirmed" && (
          <span className="value-chip" data-kind="confirmed">
            {labels.confirmed}
          </span>
        )}
      </span>
    );
  }
  if (required) {
    return (
      <span className="field-value" data-state="missing">
        {missingLabel}
      </span>
    );
  }
  return <span className="field-value" data-state="optional">—</span>;
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
        className="mb-3 text-sm font-semibold"
        style={{ color: "var(--ink)" }}
      >
        Cover Page Summary
      </h2>
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-2 text-sm">
        {entries.map(([key, value]) => (
          <div key={key} className="contents">
            <dt className="font-medium" style={{ color: "var(--ink)" }}>
              {key}
            </dt>
            <dd style={{ color: "var(--ink)" }}>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
