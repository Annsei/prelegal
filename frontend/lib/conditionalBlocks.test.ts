import { describe, expect, it } from "vitest";
import type { DocManifest } from "@/lib/docManifest";
import {
  applyConditionalBlocks,
  ConditionalTemplateError,
} from "@/lib/conditionalBlocks";

const MANIFEST: DocManifest = {
  doc_id: "conditional-test",
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
  ],
};

function block(condition: unknown): string {
  return `<!-- when ${JSON.stringify(condition)} -->\n条件条款\n<!-- endwhen -->\n`;
}

describe("conditional template blocks", () => {
  it.each([
    [{ field: "模式", value: "付费" }, { 模式: "付费" }, true],
    [{ field: "模式", op: "equals", value: "付费" }, { 模式: "免费" }, false],
    [{ field: "模式", op: "not_equals", value: "免费" }, { 模式: "付费" }, true],
    [{ field: "模式", op: "in", values: ["付费"] }, { 模式: "付费" }, true],
    [{ field: "模式", op: "exists" }, { 模式: "付费" }, true],
    [{ field: "模式", op: "exists", value: "ignored" }, { 模式: "付费" }, true],
    [{ field: "模式", op: "exists" }, {}, true],
  ])("uses shared semantics for %j", (condition, values, visible) => {
    const rendered = applyConditionalBlocks(block(condition), MANIFEST, values);
    expect(rendered.includes("条件条款")).toBe(visible);
  });

  it("keeps a block visible while its driver is unconfirmed", () => {
    expect(
      applyConditionalBlocks(
        block({ field: "模式", op: "equals", value: "付费" }),
        MANIFEST,
        {},
      ),
    ).toContain("条件条款");
  });

  it.each([
    [{ field: "模式", op: "", value: "付费" }],
    [{ field: "模式", op: null, value: "付费" }],
    [{ field: "模式", op: [], value: "付费" }],
    [{ field: "模式", op: {}, value: "付费" }],
    [{ field: "模式", op: "unknown", value: "付费" }],
    [{ field: "", op: "exists" }],
    [{ field: "unknown", op: "exists" }],
    [{ field: "模式", op: "equals" }],
    [{ field: "模式", op: "not_equals" }],
    [{ field: "模式", op: "in", values: [] }],
    [{ field: "模式", op: "in", values: ["付费", 1] }],
    [null],
    [[]],
  ])("rejects malformed condition %j", (condition) => {
    expect(() => applyConditionalBlocks(block(condition), MANIFEST, {})).toThrow(
      ConditionalTemplateError,
    );
  });

  it.each([
    [
      '<!-- when {"field":"模式","op":"exists"} -->\n' +
        '<!-- when {"field":"模式","op":"exists"} -->\n' +
        "nested\n<!-- endwhen -->\n<!-- endwhen -->",
    ],
    ['<!-- when {"field":"模式","op":"exists"} -->\nunclosed'],
    ["<!-- endwhen -->\nunmatched"],
    ['<!-- when {not-json} -->\nbad\n<!-- endwhen -->'],
  ])("rejects malformed marker structure", (source) => {
    expect(() => applyConditionalBlocks(source, MANIFEST, {})).toThrow(
      ConditionalTemplateError,
    );
  });
});
