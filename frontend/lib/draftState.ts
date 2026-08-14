import type { DocManifest, RequiredWhenCondition } from "@/lib/docManifest";

export type FieldStatus =
  | "confirmed"
  | "pending_confirmation"
  | "conflict"
  | "missing";

export const CONDITION_OPERATORS = [
  "equals",
  "not_equals",
  "in",
  "exists",
] as const;

export type FieldProvenance = {
  patch_id: string;
  source: "llm" | "user" | "form" | "system";
  actor_user_id?: number | null;
  operation: string;
  value?: string | null;
  client_source?: string | null;
  message_index?: number | null;
  message_index_trust?: "none" | "client_asserted" | "server_verified";
  at?: string | null;
};

export type DraftFieldConflict = {
  proposed_value: string;
  base_value?: string | null;
  provenance: FieldProvenance;
};

export type DraftFieldState = {
  key: string;
  status: FieldStatus;
  value?: string | null;
  revision: number;
  provenance: FieldProvenance[];
  confirmed_at?: string | null;
  confirmed_by_user_id?: number | null;
  conflict?: DraftFieldConflict | null;
};

export type DraftStateSnapshot = {
  schema_version: "draft-state.v1";
  manifest_version?: number | string | null;
  doc_id: string;
  revision: number;
  fields: Record<string, DraftFieldState>;
  validation_errors?: unknown[];
  applied_patches?: Record<string, unknown>;
};

export function readDraftStateSnapshot(
  value: unknown,
): DraftStateSnapshot | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Partial<DraftStateSnapshot>;
  if (raw.schema_version !== "draft-state.v1") return null;
  if (typeof raw.doc_id !== "string") return null;
  if (typeof raw.revision !== "number") return null;
  if (!raw.fields || typeof raw.fields !== "object") return null;
  return raw as DraftStateSnapshot;
}

export function stableFieldValues(
  manifest: DocManifest,
  snapshot: DraftStateSnapshot | null,
  fallback: Record<string, string> = {},
): Record<string, string> {
  if (!snapshot) return fallback;
  const values: Record<string, string> = {};
  for (const field of manifest.fields) {
    const state = snapshot.fields[field.key];
    if (typeof state?.value !== "string") continue;
    const value = state.value.trim();
    if (!value) continue;
    const choices = field.enum ?? field.options;
    if (choices?.length && !choices.includes(value)) continue;
    if (state.status === "confirmed") {
      values[field.key] = value;
    } else if (state.status === "conflict" && state.confirmed_at) {
      values[field.key] = value;
    }
  }
  return values;
}

export function displayFieldValues(
  manifest: DocManifest,
  snapshot: DraftStateSnapshot | null,
  fallback: Record<string, string> = {},
): Record<string, string> {
  if (!snapshot) return fallback;
  const values: Record<string, string> = {};
  for (const field of manifest.fields) {
    const state = snapshot.fields[field.key];
    if (state?.value) values[field.key] = state.value;
  }
  return values;
}

export function unresolvedRequiredKeys(
  manifest: DocManifest,
  snapshot: DraftStateSnapshot | null,
): string[] {
  const requiredKeys = requiredFieldKeys(manifest, snapshot);
  if (!snapshot) {
    return requiredKeys;
  }
  return manifest.fields
    .filter((field) => requiredKeys.includes(field.key))
    .filter((field) => {
      const state = snapshot.fields[field.key];
      const value = typeof state?.value === "string" ? state.value.trim() : "";
      const choices = field.enum ?? field.options;
      return (
        state?.status !== "confirmed" ||
        value === "" ||
        Boolean(choices?.length && !choices.includes(value))
      );
    })
    .map((field) => field.key);
}

export function isCompleteForDownload(
  manifest: DocManifest,
  snapshot: DraftStateSnapshot | null,
): boolean {
  return unresolvedRequiredKeys(manifest, snapshot).length === 0;
}

export function requiredFieldKeys(
  manifest: DocManifest,
  snapshot: DraftStateSnapshot | null,
): string[] {
  // Mirrors backend `required_field_keys` for responsive UI. The server
  // download endpoint remains authoritative before file export.
  const stableValues = stableFieldValues(manifest, snapshot, {});
  return manifest.fields
    .filter(
      (field) =>
        field.required || requiredWhenMatches(field.required_when, stableValues),
    )
    .map((field) => field.key);
}

function requiredWhenMatches(
  condition: RequiredWhenCondition | RequiredWhenCondition[] | undefined,
  stableValues: Record<string, string>,
): boolean {
  if (!condition) return false;
  const conditions = Array.isArray(condition) ? condition : [condition];
  return conditions.every((item) => singleConditionMatches(item, stableValues));
}

export function singleConditionMatches(
  condition: RequiredWhenCondition,
  stableValues: Record<string, string>,
): boolean {
  const value = stableValues[condition.field];
  const raw = condition as RequiredWhenCondition & Record<string, unknown>;
  const op = Object.hasOwn(raw, "op") ? raw.op : "equals";
  if (typeof op !== "string") return false;
  if (op === "equals") return value === condition.value;
  if (op === "not_equals") return value !== undefined && value !== condition.value;
  if (op === "in") return value !== undefined && (condition.values ?? []).includes(value);
  if (op === "exists") return Boolean(value);
  return false;
}
