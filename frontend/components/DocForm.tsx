"use client";

import { useEffect, useState } from "react";
import type { Locale } from "@/lib/i18n";
import { useDictionary } from "@/lib/i18n";
import {
  localized,
  type DocManifest,
  type ManifestField,
} from "@/lib/docManifest";
import type { DraftFieldState } from "@/lib/draftState";

type Props = {
  locale: Locale;
  manifest: DocManifest;
  values: Record<string, string>;
  fieldStates?: Record<string, DraftFieldState>;
  onConfirm: (key: string, value: string) => void | Promise<void>;
  onReject?: (key: string) => void | Promise<void>;
};

const EMPTY_FIELD_STATES: Record<string, DraftFieldState> = {};

/**
 * Manifest-driven manual-edit form — the generic counterpart of MNDAForm.
 * One input per cover-page field, grouped by manifest section. Typing edits
 * local input state; the server-owned field state changes only when the user
 * explicitly confirms or rejects a value.
 */
export function DocForm({
  locale,
  manifest,
  values,
  fieldStates = EMPTY_FIELD_STATES,
  onConfirm,
  onReject,
}: Props) {
  const t = useDictionary(locale);
  const [draftValues, setDraftValues] = useState<Record<string, string>>(values);

  useEffect(() => {
    const next: Record<string, string> = {};
    for (const field of manifest.fields) {
      const state = fieldStates[field.key];
      if (state?.status === "conflict" && state.conflict?.proposed_value) {
        next[field.key] = state.conflict.proposed_value;
      } else if (state?.value) {
        next[field.key] = state.value;
      } else {
        next[field.key] = values[field.key] ?? "";
      }
    }
    setDraftValues(next);
  }, [fieldStates, manifest.fields, values]);

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
              className="mb-2 flex w-full items-center gap-2 text-sm font-semibold"
              style={{ color: "var(--ink)" }}
            >
              {localized(section.label, locale)}
            </legend>
            <div className="space-y-3">
              {sectionFields.map((field) => (
                <Field
                  key={field.key}
                  locale={locale}
                  field={field}
                  value={draftValues[field.key] ?? ""}
                  fieldState={fieldStates[field.key]}
                  requiredLabel={t.docForm.required}
                  labels={t.docForm}
                  onChange={(value) =>
                    setDraftValues((prev) => ({ ...prev, [field.key]: value }))
                  }
                  onConfirm={() =>
                    onConfirm(field.key, draftValues[field.key] ?? "")
                  }
                  onReject={
                    onReject ? () => onReject(field.key) : undefined
                  }
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
  fieldState,
  requiredLabel,
  labels,
  onChange,
  onConfirm,
  onReject,
}: {
  locale: Locale;
  field: ManifestField;
  value: string;
  fieldState?: DraftFieldState;
  requiredLabel: string;
  labels: {
    confirm: string;
    reject: string;
    pending: string;
    confirmed: string;
    conflict: string;
    current: string;
    candidate: string;
    emptyMissingConfirmDisabled: string;
  };
  onChange: (value: string) => void;
  onConfirm: () => void | Promise<void>;
  onReject?: () => void | Promise<void>;
}) {
  const inputId = `docform-${field.key.replaceAll(" ", "-").toLowerCase()}`;
  const confirmHelpId = `${inputId}-confirm-help`;
  const hint = localized(field.hint, locale);
  const confirmDisabled =
    (!fieldState || fieldState.status === "missing") && value.trim() === "";
  const statusLabel =
    fieldState?.status === "pending_confirmation"
      ? labels.pending
      : fieldState?.status === "confirmed"
        ? labels.confirmed
        : fieldState?.status === "conflict"
          ? labels.conflict
          : "";
  const common = {
    id: inputId,
    value,
    placeholder: field.example ?? "",
    onChange: (
      e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
    ) => onChange(e.target.value),
    className: "input-field",
  } as const;

  return (
    <div>
      <label
        htmlFor={inputId}
        className="mb-1 block text-xs font-medium"
        style={{ color: "var(--ink)" }}
      >
        {localized(field.label, locale)}
        {field.required && (
          <span className="ml-1" style={{ color: "#8a1f1f" }}>
            {requiredLabel}
          </span>
        )}
        {statusLabel && (
          <span
            className="ml-2 rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase"
            style={{
              borderColor: "var(--rule)",
              color:
                fieldState?.status === "conflict"
                  ? "#8a1f1f"
                  : "var(--purple)",
            }}
          >
            {statusLabel}
          </span>
        )}
      </label>
      {field.type === "text" ? (
        <textarea rows={2} {...common} />
      ) : (
        <input type={field.type === "date" ? "date" : "text"} {...common} />
      )}
      {fieldState?.status === "conflict" && fieldState.conflict && (
        <div className="mt-1 space-y-0.5 text-xs" style={{ color: "var(--ink-3)" }}>
          <p>
            {labels.current}: {fieldState.conflict.base_value ?? fieldState.value}
          </p>
          <p>
            {labels.candidate}: {fieldState.conflict.proposed_value}
          </p>
        </div>
      )}
      {hint && (
        <p className="mt-1 text-xs" style={{ color: "var(--ink-3)" }}>
          {hint}
        </p>
      )}
      <div className="mt-2 flex gap-2">
        {confirmDisabled && (
          <span id={confirmHelpId} className="sr-only">
            {labels.emptyMissingConfirmDisabled}
          </span>
        )}
        <button
          type="button"
          className="btn btn-primary px-3 py-1 text-xs"
          disabled={confirmDisabled}
          title={confirmDisabled ? labels.emptyMissingConfirmDisabled : undefined}
          aria-describedby={confirmDisabled ? confirmHelpId : undefined}
          onClick={() => void onConfirm()}
        >
          {labels.confirm}
        </button>
        {onReject &&
          fieldState?.status &&
          ["pending_confirmation", "conflict"].includes(fieldState.status) && (
            <button
              type="button"
              className="btn btn-ghost px-3 py-1 text-xs"
              onClick={() => void onReject()}
            >
              {labels.reject}
            </button>
          )}
      </div>
    </div>
  );
}
