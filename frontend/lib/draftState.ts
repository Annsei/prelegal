import type { DocManifest, RequiredWhenCondition } from "@/lib/docManifest";

export type FieldStatus =
  | "confirmed"
  | "pending_confirmation"
  | "conflict"
  | "missing";

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
    if (state.status === "confirmed") {
      values[field.key] = state.value;
    } else if (state.status === "conflict" && state.confirmed_at) {
      values[field.key] = state.value;
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
      return state?.status !== "confirmed" || !state.value;
    })
    .map((field) => field.key);
}

export function isCompleteForDownload(
  manifest: DocManifest,
  snapshot: DraftStateSnapshot | null,
): boolean {
  return unresolvedRequiredKeys(manifest, snapshot).length === 0;
}

function requiredFieldKeys(
  manifest: DocManifest,
  snapshot: DraftStateSnapshot | null,
): string[] {
  // Mirrors backend `required_field_keys` for responsive UI; the
  // The server download endpoint remains authoritative before file export.
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
  const op = condition.op ?? "equals";
  if (op === "equals") return value === condition.value;
  if (op === "not_equals") return value !== undefined && value !== condition.value;
  if (op === "in") return value !== undefined && (condition.values ?? []).includes(value);
  if (op === "exists") return Boolean(value);
  return false;
}
