import { describe, expect, it } from "vitest";
import {
  allRequiredFilled,
  annotateTermRefs,
  extraFields,
  missingRequired,
  type DocManifest,
} from "./docManifest";

const MANIFEST: DocManifest = {
  doc_id: "cloud-service-agreement",
  version: 1,
  sections: [
    { key: "parties", label: { zh: "当事方", en: "Parties" } },
    { key: "keyterms", label: { zh: "关键条款", en: "Key Terms" } },
  ],
  fields: [
    {
      key: "Customer",
      section: "parties",
      type: "string",
      required: true,
      label: { zh: "客户", en: "Customer" },
      aliases: ["Customer’s"],
    },
    {
      key: "Governing Law",
      section: "keyterms",
      type: "string",
      required: true,
      label: { zh: "适用法律", en: "Governing Law" },
    },
    {
      key: "DPA",
      section: "keyterms",
      type: "string",
      required: false,
      label: { zh: "数据处理协议", en: "DPA" },
    },
  ],
};

describe("missingRequired / allRequiredFilled", () => {
  it("reports required fields with no value; optional ones never block", () => {
    expect(missingRequired(MANIFEST, {}).map((f) => f.key)).toEqual([
      "Customer",
      "Governing Law",
    ]);
    // Whitespace-only doesn't count as filled.
    expect(
      missingRequired(MANIFEST, { Customer: "  " }).map((f) => f.key),
    ).toEqual(["Customer", "Governing Law"]);
    expect(
      allRequiredFilled(MANIFEST, {
        Customer: "Acme",
        "Governing Law": "Delaware",
      }),
    ).toBe(true);
    // DPA (optional) missing does not block completion.
  });
});

describe("extraFields", () => {
  it("returns chat-collected keys the manifest doesn't declare", () => {
    expect(
      extraFields(MANIFEST, {
        Customer: "Acme",
        "Some Side Letter": "Attached",
        Empty: "  ",
      }),
    ).toEqual([["Some Side Letter", "Attached"]]);
  });
});

describe("annotateTermRefs", () => {
  const body =
    'x <span class="coverpage_link">Customer</span> ' +
    'y <span class="coverpage_link">Customer’s</span> ' +
    'z <span class="keyterms_link">Governing Law</span> ' +
    'w <span class="keyterms_link">Unknown Term</span>';

  it("marks references as defined (with tooltip value) or missing", () => {
    const out = annotateTermRefs(body, MANIFEST, { Customer: "Acme, Inc." });
    // Canonical key and its alias both resolve to the same filled field.
    expect(out).toContain(
      '<span class="coverpage_link term-defined" title="Customer: Acme, Inc.">Customer</span>',
    );
    expect(out).toContain(
      'title="Customer: Acme, Inc.">Customer’s</span>',
    );
    // Required-but-unfilled reference flagged as missing.
    expect(out).toContain(
      '<span class="keyterms_link term-missing">Governing Law</span>',
    );
    // Span text not in the manifest is left untouched.
    expect(out).toContain('<span class="keyterms_link">Unknown Term</span>');
  });

  it("escapes values that would break out of the title attribute", () => {
    const out = annotateTermRefs(body, MANIFEST, {
      Customer: 'Acme "A&B" <Inc>',
    });
    expect(out).toContain(
      'title="Customer: Acme &quot;A&amp;B&quot; &lt;Inc&gt;"',
    );
    expect(out).not.toContain('title="Customer: Acme "');
  });

  it("is a no-op without a manifest", () => {
    expect(annotateTermRefs(body, null, { Customer: "Acme" })).toBe(body);
  });
});
