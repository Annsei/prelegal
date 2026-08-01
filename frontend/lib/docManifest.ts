// Cover-page field manifests (templates/manifests/<doc_id>.json, served
// inside GET /api/templates/{doc_id}). One manifest drives the manual-edit
// form, the rendered Cover Page, download gating, and the highlighting of
// term references in the standard-terms body.

import type { Locale } from "@/lib/i18n";

export type LocalizedText = { zh: string; en: string };

export type ManifestFieldType = "string" | "text" | "date";

export type RequiredWhenCondition = {
  field: string;
  op?: "equals" | "not_equals" | "in" | "exists";
  value?: string;
  values?: string[];
};

export type ManifestField = {
  key: string;
  section: string;
  type: ManifestFieldType;
  required: boolean;
  required_when?: RequiredWhenCondition | RequiredWhenCondition[];
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
  /<span\b(?=[^>]*\bclass="[^"]*\b(?:coverpage_link|orderform_link|keyterms_link)\b[^"]*")([^>]*)>([^<]+)<\/span>/g;
const TERM_CLASS_RE = /\b(coverpage_link|orderform_link|keyterms_link)\b/;
const CLASS_ATTR_RE = /\bclass="([^"]*)"/;
const TITLE_ATTR_RE = /\s+title="[^"]*"/g;

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
  return markdown.replace(TERM_REF_RE, (match, attrs: string, text: string) => {
    if (!hasTermRefClass(attrs)) return match;
    const field = lookup.get(text);
    if (!field) return match;
    const value = filledValue(fields, field.key);
    const nextAttrs = addTermStateClass(
      attrs.replace(TITLE_ATTR_RE, ""),
      value ? "term-defined" : "term-missing",
    );
    if (value) {
      return `<span${nextAttrs} title="${escapeAttr(
        `${field.key}: ${value}`,
      )}">${text}</span>`;
    }
    return `<span${nextAttrs}>${text}</span>`;
  });
}

function hasTermRefClass(attrs: string): boolean {
  const match = attrs.match(CLASS_ATTR_RE);
  return Boolean(match?.[1]?.match(TERM_CLASS_RE));
}

function addTermStateClass(attrs: string, stateClass: string): string {
  return attrs.replace(CLASS_ATTR_RE, (_match, classValue: string) => {
    const classes = new Set(classValue.split(/\s+/).filter(Boolean));
    classes.add(stateClass);
    return `class="${Array.from(classes).join(" ")}"`;
  });
}

function escapeAttr(raw: string): string {
  return raw
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}
