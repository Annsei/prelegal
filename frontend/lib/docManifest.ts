// Cover-page field manifests (templates/manifests/<doc_id>.json, served
// inside GET /api/templates/{doc_id}). One manifest drives the manual-edit
// form, the rendered Cover Page, download gating, and the highlighting of
// term references in the standard-terms body.

import type { Locale } from "@/lib/i18n";

export type LocalizedText = { zh: string; en: string };

export type ManifestFieldType = "string" | "text" | "date";

export type ManifestField = {
  key: string;
  section: string;
  type: ManifestFieldType;
  required: boolean;
  label: LocalizedText;
  hint?: LocalizedText;
  example?: string;
  aliases?: string[];
};

export type ManifestSection = {
  key: string;
  label: LocalizedText;
};

export type DocManifest = {
  doc_id: string;
  version: number;
  sections: ManifestSection[];
  fields: ManifestField[];
};

export function localized(text: LocalizedText | undefined, locale: Locale): string {
  if (!text) return "";
  return text[locale] || text.en || text.zh || "";
}

function filledValue(fields: Record<string, string>, key: string): string {
  const value = fields[key];
  return typeof value === "string" ? value.trim() : "";
}

export function missingRequired(
  manifest: DocManifest,
  fields: Record<string, string>,
): ManifestField[] {
  return manifest.fields.filter(
    (field) => field.required && filledValue(fields, field.key) === "",
  );
}

export function allRequiredFilled(
  manifest: DocManifest,
  fields: Record<string, string>,
): boolean {
  return missingRequired(manifest, fields).length === 0;
}

/** Field values the chat collected that aren't declared in the manifest —
 * shown separately so nothing the user said silently disappears. */
export function extraFields(
  manifest: DocManifest,
  fields: Record<string, string>,
): Array<[string, string]> {
  const known = new Set(manifest.fields.map((field) => field.key));
  return Object.entries(fields).filter(
    ([key, value]) => !known.has(key) && value && value.trim() !== "",
  );
}

// Term-reference spans in Common Paper standard terms:
//   <span class="coverpage_link">Customer</span>
//   <span class="orderform_link">Subscription Period</span>
//   <span class="keyterms_link">Governing Law</span>
// The body references cover-page terms BY NAME (they are links to the
// cover page in Common Paper's own product) — we must not substitute
// values inline, only mark each reference as defined or still missing.
const TERM_REF_RE =
  /<span class="(coverpage_link|orderform_link|keyterms_link)">([^<]+)<\/span>/g;

/** Map every span text (canonical key or alias) to its manifest field. */
export function buildTermLookup(
  manifest: DocManifest,
): Map<string, ManifestField> {
  const lookup = new Map<string, ManifestField>();
  for (const field of manifest.fields) {
    lookup.set(field.key, field);
    for (const alias of field.aliases ?? []) {
      lookup.set(alias, field);
    }
  }
  return lookup;
}

/**
 * Annotate term-reference spans in the raw template markdown before it is
 * handed to `marked`: references whose cover-page field has a value gain
 * `term-defined` (with the value in the tooltip), the rest gain
 * `term-missing`. Span texts that don't match any manifest field (or when
 * there is no manifest) are left untouched.
 */
export function annotateTermRefs(
  markdown: string,
  manifest: DocManifest | null | undefined,
  fields: Record<string, string>,
): string {
  if (!manifest) return markdown;
  const lookup = buildTermLookup(manifest);
  return markdown.replace(TERM_REF_RE, (match, cls: string, text: string) => {
    const field = lookup.get(text);
    if (!field) return match;
    const value = filledValue(fields, field.key);
    if (value) {
      return `<span class="${cls} term-defined" title="${escapeAttr(
        `${field.key}: ${value}`,
      )}">${text}</span>`;
    }
    return `<span class="${cls} term-missing">${text}</span>`;
  });
}

function escapeAttr(raw: string): string {
  return raw
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}
