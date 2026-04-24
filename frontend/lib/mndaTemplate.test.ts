import { describe, expect, it } from "vitest";
import {
  ATTRIBUTION_LICENSE_URL,
  ATTRIBUTION_VERSION_URL,
  parseSegments,
  type PlaceholderKey,
  STANDARD_TERMS_SECTIONS,
} from "./mndaTemplate";

describe("STANDARD_TERMS_SECTIONS", () => {
  it("has all 11 sections in the upstream order", () => {
    expect(STANDARD_TERMS_SECTIONS).toHaveLength(11);
    expect(STANDARD_TERMS_SECTIONS.map((s) => s.heading)).toEqual([
      "Introduction",
      "Use and Protection of Confidential Information",
      "Exceptions",
      "Disclosures Required by Law",
      "Term and Termination",
      "Return or Destruction of Confidential Information",
      "Proprietary Rights",
      "Disclaimer",
      "Governing Law and Jurisdiction",
      "Equitable Relief",
      "General",
    ]);
  });

  it("tokenizes the three Section 5 cover-page references", () => {
    // Regression: upstream markdown has three <span class="coverpage_link">
    // anchors in "Term and Termination" (Effective Date, MNDA Term, Term of
    // Confidentiality). Early implementation hard-coded the labels as plain
    // text, breaking flow-through of form state.
    const section5 = STANDARD_TERMS_SECTIONS[4];
    expect(section5.heading).toBe("Term and Termination");
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

describe("Attribution URLs", () => {
  it("links to the upstream versioned Common Paper standard", () => {
    expect(ATTRIBUTION_VERSION_URL).toBe(
      "https://commonpaper.com/standards/mutual-nda/1.0/",
    );
  });

  it("links to the CC BY 4.0 license text", () => {
    expect(ATTRIBUTION_LICENSE_URL).toBe(
      "https://creativecommons.org/licenses/by/4.0/",
    );
  });
});
