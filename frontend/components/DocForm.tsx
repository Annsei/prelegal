"use client";

import type { Locale } from "@/lib/i18n";
import { useDictionary } from "@/lib/i18n";
import {
  localized,
  type DocManifest,
  type ManifestField,
} from "@/lib/docManifest";

type Props = {
  locale: Locale;
  manifest: DocManifest;
  values: Record<string, string>;
  onChange: (key: string, value: string) => void;
};

/**
 * Manifest-driven manual-edit form — the generic counterpart of MNDAForm.
 * One input per cover-page field, grouped by manifest section. Values live
 * in the page's `genericFields` map (the same store the AI chat writes
 * into), so chat collection and manual edits compose freely.
 */
export function DocForm({ locale, manifest, values, onChange }: Props) {
  const t = useDictionary(locale);

  return (
    <div className="space-y-6">
      {manifest.sections.map((section) => {
        const sectionFields = manifest.fields.filter(
          (field) => field.section === section.key,
        );
        if (sectionFields.length === 0) return null;
        return (
          <fieldset key={section.key}>
            <legend
              className="mb-2 text-sm font-semibold"
              style={{ color: "#032147" }}
            >
              {localized(section.label, locale)}
            </legend>
            <div className="space-y-3">
              {sectionFields.map((field) => (
                <Field
                  key={field.key}
                  locale={locale}
                  field={field}
                  value={values[field.key] ?? ""}
                  requiredLabel={t.docForm.required}
                  onChange={(value) => onChange(field.key, value)}
                />
              ))}
            </div>
          </fieldset>
        );
      })}
    </div>
  );
}

function Field({
  locale,
  field,
  value,
  requiredLabel,
  onChange,
}: {
  locale: Locale;
  field: ManifestField;
  value: string;
  requiredLabel: string;
  onChange: (value: string) => void;
}) {
  const inputId = `docform-${field.key.replaceAll(" ", "-").toLowerCase()}`;
  const hint = localized(field.hint, locale);
  const common = {
    id: inputId,
    value,
    placeholder: field.example ?? "",
    onChange: (
      e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
    ) => onChange(e.target.value),
    className:
      "w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm shadow-sm focus:outline-none",
  } as const;

  return (
    <div>
      <label
        htmlFor={inputId}
        className="mb-1 block text-xs font-medium"
        style={{ color: "#032147" }}
      >
        {localized(field.label, locale)}
        {field.required && (
          <span className="ml-1" style={{ color: "#8a1f1f" }}>
            {requiredLabel}
          </span>
        )}
      </label>
      {field.type === "text" ? (
        <textarea rows={2} {...common} />
      ) : (
        <input type={field.type === "date" ? "date" : "text"} {...common} />
      )}
      {hint && (
        <p className="mt-1 text-xs" style={{ color: "#888888" }}>
          {hint}
        </p>
      )}
    </div>
  );
}
