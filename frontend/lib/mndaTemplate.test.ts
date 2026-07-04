import { describe, expect, it } from "vitest";
import {
  parseSegments,
  type PlaceholderKey,
  STANDARD_TERMS_SECTIONS,
  TEMPLATE_NOTICE,
  TEMPLATE_VERSION_LABEL,
} from "./mndaTemplate";

describe("STANDARD_TERMS_SECTIONS", () => {
  it("has all 11 sections of the PRC template in order", () => {
    expect(STANDARD_TERMS_SECTIONS).toHaveLength(11);
    expect(STANDARD_TERMS_SECTIONS.map((s) => s.heading)).toEqual([
      "协议构成",
      "保密信息的使用与保护",
      "除外情形",
      "依法披露",
      "期限与终止",
      "返还与销毁",
      "权利保留",
      "不作保证",
      "违约责任",
      "适用法律与争议解决",
      "其他约定",
    ]);
  });

  it("tokenizes the three term-section cover-page references", () => {
    // Regression: the term section carries three placeholders (生效日期、
    // 协议期限、保密期限). Early implementations hard-coded the labels as
    // plain text, breaking flow-through of form state.
    const section5 = STANDARD_TERMS_SECTIONS[4];
    expect(section5.heading).toBe("期限与终止");
    expect(section5.body).toContain("{{effectiveDate}}");
    expect(section5.body).toContain("{{mndaTerm}}");
    expect(section5.body).toContain("{{confidentialityTerm}}");
  });

  it("tokenizes purpose, governing law, and jurisdiction references", () => {
    const allBodies = STANDARD_TERMS_SECTIONS.map((s) => s.body).join("\n");
    expect(allBodies).toContain("{{purpose}}");
    expect(allBodies).toContain("{{governingLaw}}");
    expect(allBodies).toContain("{{jurisdiction}}");
  });

  it("uses no stale raw {{…}} tokens outside the known placeholder set", () => {
    const known = new Set<PlaceholderKey>([
      "purpose",
      "governingLaw",
      "jurisdiction",
      "effectiveDate",
      "mndaTerm",
      "confidentialityTerm",
    ]);
    const re = /{{([a-zA-Z]+)}}/g;
    for (const section of STANDARD_TERMS_SECTIONS) {
      let m: RegExpExecArray | null;
      while ((m = re.exec(section.body)) !== null) {
        expect(known.has(m[1] as PlaceholderKey)).toBe(true);
      }
    }
  });
});

describe("parseSegments", () => {
  it("splits a body into text, bold, and placeholder segments in order", () => {
    const segments = parseSegments(
      'hello **world** and {{purpose}} plus {{governingLaw}} end',
    );
    expect(segments).toEqual([
      { type: "text", value: "hello " },
      { type: "bold", value: "world" },
      { type: "text", value: " and " },
      { type: "placeholder", key: "purpose" },
      { type: "text", value: " plus " },
      { type: "placeholder", key: "governingLaw" },
      { type: "text", value: " end" },
    ]);
  });

  it("emits empty output for empty input", () => {
    expect(parseSegments("")).toEqual([]);
  });

  it("emits a single text segment for input with no tokens", () => {
    expect(parseSegments("just plain prose")).toEqual([
      { type: "text", value: "just plain prose" },
    ]);
  });

  it("handles consecutive placeholders without dropping intervening text", () => {
    const segments = parseSegments("{{purpose}} then {{purpose}}");
    expect(segments).toEqual([
      { type: "placeholder", key: "purpose" },
      { type: "text", value: " then " },
      { type: "placeholder", key: "purpose" },
    ]);
  });

  it("is idempotent on successive calls (lastIndex is reset)", () => {
    // Regression guard: global regex state can bleed across calls if the
    // function does not reset `lastIndex`.
    const input = "**bold** {{purpose}}";
    const first = parseSegments(input);
    const second = parseSegments(input);
    expect(second).toEqual(first);
  });

  it("covers every section body without throwing", () => {
    for (const section of STANDARD_TERMS_SECTIONS) {
      expect(() => parseSegments(section.body)).not.toThrow();
      const segments = parseSegments(section.body);
      expect(segments.length).toBeGreaterThan(0);
    }
  });
});

describe("Template provenance", () => {
  it("labels the template as the Prelegal PRC draft v1.0", () => {
    expect(TEMPLATE_VERSION_LABEL).toContain("Prelegal");
    expect(TEMPLATE_VERSION_LABEL).toContain("v1.0");
  });

  it("carries the lawyer-review notice", () => {
    expect(TEMPLATE_NOTICE).toContain("律师审核");
  });
});
