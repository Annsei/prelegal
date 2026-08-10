import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type { DocManifest } from "@/lib/docManifest";
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

type ConditionAssignment = {
  id: string;
  values: Record<string, string>;
  unconfirmed?: string[];
  expected_active: string[];
};

type ConditionVector = {
  id: string;
  manifest?: DocManifest;
  manifest_doc_id?: string;
  positive_witness: "possible" | "impossible";
  assignments: ConditionAssignment[];
};

const CONDITION_VECTORS = (
  JSON.parse(
    readFileSync(
      resolve(
        process.cwd(),
        "../backend/quality_evals/condition_conformance.json",
      ),
      "utf8",
    ),
  ) as { schema_version: number; vectors: ConditionVector[] }
).vectors;

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

  for (const manifest of MANIFESTS.filter((item) =>
    item.fields.some((field) => field.required),
  )) {
    it(`${manifest.doc_id} treats whitespace-only required values as unresolved`, () => {
      const snapshot = missingSnapshot(manifest);
      const required = manifest.fields.filter((item) => item.required);
      expect(required.length).toBeGreaterThan(0);
      for (const field of required) {
        snapshot.fields[field.key] = { ...confirmed("   "), key: field.key };
      }

      expect(unresolvedRequiredKeys(manifest, snapshot)).toEqual(
        required.map((field) => field.key),
      );
    });
  }

  for (const vector of CONDITION_VECTORS) {
    it(`matches shared condition vector ${vector.id}`, () => {
      const manifest =
        vector.manifest ??
        MANIFESTS.find((item) => item.doc_id === vector.manifest_doc_id);
      expect(manifest).toBeDefined();
      if (vector.positive_witness === "impossible") {
        expect(vector.assignments).toEqual([]);
        return;
      }
      const conditionalKeys = new Set(
        manifest!.fields
          .filter((field) => field.required_when)
          .map((field) => field.key),
      );
      for (const assignment of vector.assignments) {
        const snapshot = snapshotWithConfirmed(manifest!, assignment.values);
        for (const key of assignment.unconfirmed ?? []) {
          snapshot.fields[key] = {
            ...snapshot.fields[key],
            status: "pending_confirmation",
            confirmed_at: null,
            confirmed_by_user_id: null,
          };
        }
        const actual = unresolvedRequiredKeys(manifest!, snapshot)
          .filter((key) => conditionalKeys.has(key))
          .sort();
        expect(actual, assignment.id).toEqual(
          [...assignment.expected_active].sort(),
        );
      }
    });
  }
});
