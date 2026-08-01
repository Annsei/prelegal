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
    {
      key: "是否自动续期",
      section: "parties",
      type: "string",
      required: false,
      label: { zh: "是否自动续期", en: "Auto-renewal" },
    },
    {
      key: "不续约通知期",
      section: "parties",
      type: "string",
      required: false,
      required_when: { field: "是否自动续期", op: "equals", value: "是" },
      label: { zh: "不续约通知期", en: "Non-renewal Notice Period" },
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
    是否自动续期: {
      key: "是否自动续期",
      status: "missing",
      value: null,
      revision: 0,
      provenance: [],
    },
    不续约通知期: {
      key: "不续约通知期",
      status: "missing",
      value: null,
      revision: 0,
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

  it("evaluates required_when from confirmed stable values only", () => {
    const pendingRenewal: DraftStateSnapshot = {
      ...SNAPSHOT,
      fields: {
        ...SNAPSHOT.fields,
        客户: {
          ...SNAPSHOT.fields.客户,
          status: "confirmed",
          conflict: null,
        },
        服务方: {
          ...SNAPSHOT.fields.服务方,
          status: "confirmed",
        },
        是否自动续期: {
          key: "是否自动续期",
          status: "pending_confirmation",
          value: "是",
          revision: 4,
          provenance: [],
        },
      },
    };
    expect(unresolvedRequiredKeys(MANIFEST, pendingRenewal)).toEqual([]);

    const confirmedRenewal: DraftStateSnapshot = {
      ...pendingRenewal,
      fields: {
        ...pendingRenewal.fields,
        是否自动续期: {
          ...pendingRenewal.fields.是否自动续期,
          status: "confirmed",
          confirmed_at: "2026-07-31T00:00:00+00:00",
          confirmed_by_user_id: 1,
        },
      },
    };
    expect(unresolvedRequiredKeys(MANIFEST, confirmedRenewal)).toEqual([
      "不续约通知期",
    ]);

    const conflictedRenewal: DraftStateSnapshot = {
      ...confirmedRenewal,
      fields: {
        ...confirmedRenewal.fields,
        是否自动续期: {
          ...confirmedRenewal.fields.是否自动续期,
          status: "conflict",
          value: "是",
          conflict: {
            base_value: "是",
            proposed_value: "否",
            provenance: {
              patch_id: "llm-renewal",
              source: "llm",
              operation: "propose",
              value: "否",
            },
          },
        },
      },
    };
    expect(unresolvedRequiredKeys(MANIFEST, conflictedRenewal)).toEqual([
      "不续约通知期",
    ]);
  });

  it("treats confirmed empty strings as present for not_equals and in conditions", () => {
    const manifest: DocManifest = {
      ...MANIFEST,
      fields: [
        ...MANIFEST.fields,
        {
          key: "空值控制字段",
          section: "parties",
          type: "string",
          required: false,
          label: { zh: "空值控制字段", en: "Blank Control" },
        },
        {
          key: "非某值触发字段",
          section: "parties",
          type: "string",
          required: false,
          required_when: {
            field: "空值控制字段",
            op: "not_equals",
            value: "不触发",
          },
          label: { zh: "非某值触发字段", en: "Not Equals Dependent" },
        },
        {
          key: "枚举触发字段",
          section: "parties",
          type: "string",
          required: false,
          required_when: {
            field: "空值控制字段",
            op: "in",
            values: ["", "触发"],
          },
          label: { zh: "枚举触发字段", en: "In Dependent" },
        },
      ],
    };
    const snapshot: DraftStateSnapshot = {
      ...SNAPSHOT,
      fields: {
        ...SNAPSHOT.fields,
        客户: {
          ...SNAPSHOT.fields.客户,
          status: "confirmed",
          conflict: null,
        },
        服务方: {
          ...SNAPSHOT.fields.服务方,
          status: "confirmed",
        },
        空值控制字段: {
          key: "空值控制字段",
          status: "confirmed",
          value: "",
          revision: 4,
          provenance: [],
          confirmed_at: "2026-07-31T00:00:00+00:00",
          confirmed_by_user_id: 1,
        },
      },
    };

    expect(unresolvedRequiredKeys(manifest, snapshot)).toEqual([
      "非某值触发字段",
      "枚举触发字段",
    ]);
  });
});
