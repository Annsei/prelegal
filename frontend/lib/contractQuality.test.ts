import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type {
  DocManifest,
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

function matchingValue(condition: RequiredWhenCondition): string {
  if ((condition.op ?? "equals") === "equals") return condition.value ?? "";
  if (condition.op === "not_equals") return "确定性非匹配基值";
  if (condition.op === "in") return condition.values?.[0] ?? "";
  return "已存在";
}

function nonmatchingValue(condition: RequiredWhenCondition): string | null {
  if ((condition.op ?? "equals") === "equals") return "确定性不命中值";
  if (condition.op === "not_equals") return condition.value ?? "";
  if (condition.op === "in") return "确定性不命中值";
  return null;
}

describe("manifest contract-quality mirror", () => {
  it("loads all 11 kernel-managed manifests", () => {
    expect(MANIFESTS).toHaveLength(11);
    expect(new Set(MANIFESTS.map((manifest) => manifest.doc_id)).size).toBe(11);
  });

  for (const manifest of MANIFESTS) {
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

      conditions.forEach((condition, index) => {
        it(`${manifest.doc_id} mirrors required_when for ${dependent.key} #${index}`, () => {
          const unconfirmed = missingSnapshot(manifest);
          expect(unresolvedRequiredKeys(manifest, unconfirmed)).not.toContain(
            dependent.key,
          );

          const matching = missingSnapshot(manifest);
          matching.fields[condition.field] = {
            ...confirmed(matchingValue(condition)),
            key: condition.field,
          };
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

          const nonmatch = nonmatchingValue(condition);
          if (nonmatch !== null) {
            const inactive = missingSnapshot(manifest);
            inactive.fields[condition.field] = {
              ...confirmed(nonmatch),
              key: condition.field,
            };
            expect(unresolvedRequiredKeys(manifest, inactive)).not.toContain(
              dependent.key,
            );
          }
        });
      });
    }
  }
});
