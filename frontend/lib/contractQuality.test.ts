import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type {
  DocManifest,
  ManifestField,
  RequiredWhenCondition,
} from "@/lib/docManifest";
import {
  unresolvedRequiredKeys,
  type DraftFieldState,
  type DraftStateSnapshot,
} from "@/lib/draftState";

const MANIFEST_DIRECTORY = resolve(process.cwd(), "../templates/manifests");
const MANIFESTS = readdirSync(MANIFEST_DIRECTORY)
  .filter((name) => name.endsWith(".json"))
  .sort()
  .map((name) =>
    JSON.parse(
      readFileSync(resolve(MANIFEST_DIRECTORY, name), "utf8"),
    ) as DocManifest,
  );
const SYNTHETIC_CONJUNCTION: DocManifest = {
  doc_id: "synthetic-conjunction",
  version: 1,
  sections: [{ key: "terms", label: { zh: "条款", en: "Terms" } }],
  fields: [
    {
      key: "模式",
      section: "terms",
      type: "string",
      required: false,
      label: { zh: "模式", en: "Mode" },
    },
    {
      key: "地区",
      section: "terms",
      type: "string",
      required: false,
      label: { zh: "地区", en: "Region" },
    },
    {
      key: "付款安排",
      section: "terms",
      type: "string",
      required: false,
      required_when: [
        { field: "模式", op: "equals", value: "付费" },
        { field: "地区", op: "in", values: ["境内"] },
      ],
      label: { zh: "付款安排", en: "Payment" },
    },
  ],
};
const QUALITY_MANIFESTS = [...MANIFESTS, SYNTHETIC_CONJUNCTION];

function missingSnapshot(manifest: DocManifest): DraftStateSnapshot {
  return {
    schema_version: "draft-state.v1",
    manifest_version: manifest.version,
    doc_id: manifest.doc_id,
    revision: 0,
    fields: Object.fromEntries(
      manifest.fields.map((field) => [
        field.key,
        {
          key: field.key,
          status: "missing",
          value: null,
          revision: 0,
          provenance: [],
        } satisfies DraftFieldState,
      ]),
    ),
  };
}

function confirmed(value: string): DraftFieldState {
  return {
    key: "",
    status: "confirmed",
    value,
    revision: 1,
    provenance: [],
    confirmed_at: "2026-01-15T00:00:00+00:00",
    confirmed_by_user_id: 1,
  };
}

type ConstrainedField = ManifestField & {
  enum?: string[];
  options?: string[];
};

function conditionMatches(
  condition: RequiredWhenCondition,
  value: string,
): boolean {
  const op = condition.op ?? "equals";
  if (op === "equals") return value === condition.value;
  if (op === "not_equals") return value !== condition.value;
  if (op === "in") return (condition.values ?? []).includes(value);
  return value.trim() !== "";
}

function witnessCandidates(
  field: ConstrainedField,
  conditions: RequiredWhenCondition[],
): string[] {
  const choices = field.enum ?? field.options ?? [];
  const operands = conditions.flatMap((condition) => [
    ...(typeof condition.value === "string" ? [condition.value] : []),
    ...(condition.values ?? []),
  ]);
  const generated =
    field.type === "date"
      ? ["2026-01-15", "2026-01-16", "2026-01-17"]
      : [field.example ?? "", `${field.key}候选甲`, `${field.key}候选乙`];
  const candidates = choices.length > 0 ? [...choices, ...operands] : [...operands, ...generated];
  return [...new Set(candidates.filter((value) => value.trim() !== ""))];
}

function witnessAssignments(
  manifest: DocManifest,
  conditions: RequiredWhenCondition[],
  failingIndex?: number,
): Record<string, string> {
  const assignments: Record<string, string> = {};
  const grouped = new Map<string, Array<[number, RequiredWhenCondition]>>();
  conditions.forEach((condition, index) => {
    grouped.set(condition.field, [
      ...(grouped.get(condition.field) ?? []),
      [index, condition],
    ]);
  });
  for (const [key, entries] of grouped) {
    const field = manifest.fields.find((item) => item.key === key) as
      | ConstrainedField
      | undefined;
    if (!field) throw new Error(`missing condition field ${key}`);
    const candidate = witnessCandidates(
      field,
      entries.map(([, condition]) => condition),
    ).find((value) =>
      entries.every(([index, condition]) =>
        index === failingIndex
          ? !conditionMatches(condition, value)
          : conditionMatches(condition, value),
      ),
    );
    if (candidate === undefined) {
      throw new Error(`condition witness unavailable for ${key}`);
    }
    assignments[key] = candidate;
  }
  return assignments;
}

function snapshotWithConfirmed(
  manifest: DocManifest,
  values: Record<string, string>,
): DraftStateSnapshot {
  const snapshot = missingSnapshot(manifest);
  for (const [key, value] of Object.entries(values)) {
    snapshot.fields[key] = { ...confirmed(value), key };
  }
  return snapshot;
}

describe("manifest contract-quality mirror", () => {
  it("loads all 11 kernel-managed manifests", () => {
    expect(MANIFESTS).toHaveLength(11);
    expect(new Set(MANIFESTS.map((manifest) => manifest.doc_id)).size).toBe(11);
  });

  for (const manifest of QUALITY_MANIFESTS) {
    it(`${manifest.doc_id} treats whitespace-only required values as unresolved`, () => {
      const snapshot = missingSnapshot(manifest);
      for (const field of manifest.fields.filter((item) => item.required)) {
        snapshot.fields[field.key] = { ...confirmed("   "), key: field.key };
      }

      expect(unresolvedRequiredKeys(manifest, snapshot)).toEqual(
        manifest.fields.filter((field) => field.required).map((field) => field.key),
      );
    });

    for (const dependent of manifest.fields) {
      const rawConditions = dependent.required_when;
      if (!rawConditions) continue;
      const conditions = Array.isArray(rawConditions)
        ? rawConditions
        : [rawConditions];

      it(`${manifest.doc_id} mirrors required_when AND semantics for ${dependent.key}`, () => {
        const unconfirmed = missingSnapshot(manifest);
        expect(unresolvedRequiredKeys(manifest, unconfirmed)).not.toContain(
          dependent.key,
        );

        const matchedValues = witnessAssignments(manifest, conditions);
        const matching = snapshotWithConfirmed(manifest, matchedValues);
        expect(unresolvedRequiredKeys(manifest, matching)).toContain(
          dependent.key,
        );

        matching.fields[dependent.key] = {
          ...confirmed("已确认条件字段"),
          key: dependent.key,
        };
        expect(unresolvedRequiredKeys(manifest, matching)).not.toContain(
          dependent.key,
        );

        conditions.forEach((condition, index) => {
          const unconfirmedDriver = snapshotWithConfirmed(manifest, matchedValues);
          unconfirmedDriver.fields[condition.field] = {
            ...unconfirmedDriver.fields[condition.field],
            status: "pending_confirmation",
            confirmed_at: null,
          };
          expect(
            unresolvedRequiredKeys(manifest, unconfirmedDriver),
          ).not.toContain(dependent.key);

          if ((condition.op ?? "equals") === "exists") return;
          const negativeValues = witnessAssignments(manifest, conditions, index);
          const inactive = snapshotWithConfirmed(manifest, negativeValues);
          expect(unresolvedRequiredKeys(manifest, inactive)).not.toContain(
            dependent.key,
          );
        });
      });
    }
  }
});
