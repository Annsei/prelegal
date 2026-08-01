import { describe, expect, it } from "vitest";
import type { DocManifest } from "@/lib/docManifest";
import {
  displayFieldValues,
  isCompleteForDownload,
  stableFieldValues,
  unresolvedRequiredKeys,
  type DraftStateSnapshot,
} from "@/lib/draftState";

const MANIFEST: DocManifest = {
  doc_id: "cloud-service-agreement",
  version: 2,
  sections: [{ key: "parties", label: { zh: "当事方", en: "Parties" } }],
  fields: [
    {
      key: "客户",
      section: "parties",
      type: "string",
      required: true,
      label: { zh: "客户", en: "Customer" },
    },
    {
      key: "服务方",
      section: "parties",
      type: "string",
      required: true,
      label: { zh: "服务方", en: "Provider" },
    },
  ],
};

const SNAPSHOT: DraftStateSnapshot = {
  schema_version: "draft-state.v1",
  manifest_version: 2,
  doc_id: "cloud-service-agreement",
  revision: 3,
  applied_patches: {},
  fields: {
    客户: {
      key: "客户",
      status: "conflict",
      value: "原客户",
      revision: 3,
      confirmed_at: "2026-07-31T00:00:00+00:00",
      confirmed_by_user_id: 1,
      provenance: [],
      conflict: {
        base_value: "原客户",
        proposed_value: "新客户",
        provenance: {
          patch_id: "llm-2",
          source: "llm",
          operation: "propose",
          value: "新客户",
        },
      },
    },
    服务方: {
      key: "服务方",
      status: "pending_confirmation",
      value: "云服务商",
      revision: 2,
      provenance: [],
    },
  },
};

describe("draftState helpers", () => {
  it("uses confirmed conflict base values for display while blocking download", () => {
    expect(stableFieldValues(MANIFEST, SNAPSHOT)).toEqual({ 客户: "原客户" });
    expect(displayFieldValues(MANIFEST, SNAPSHOT)).toEqual({
      客户: "原客户",
      服务方: "云服务商",
    });
    expect(unresolvedRequiredKeys(MANIFEST, SNAPSHOT)).toEqual([
      "客户",
      "服务方",
    ]);
    expect(isCompleteForDownload(MANIFEST, SNAPSHOT)).toBe(false);
  });

  it("treats missing snapshots as unresolved for manifest documents", () => {
    expect(unresolvedRequiredKeys(MANIFEST, null)).toEqual(["客户", "服务方"]);
    expect(isCompleteForDownload(MANIFEST, null)).toBe(false);
  });
});
