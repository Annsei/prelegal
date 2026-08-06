import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GenericDocPreview } from "./GenericDocPreview";
import type { TemplateResponse } from "@/lib/api";
import type { DocManifest } from "@/lib/docManifest";
import type { DraftStateSnapshot } from "@/lib/draftState";
import type { TemplateLoad } from "@/lib/useDocTemplate";

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
      label: { zh: "客户", en: "Customer (company)" },
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

function readyLoad(overrides: Partial<TemplateResponse> = {}): TemplateLoad {
  return {
    kind: "ready",
    template: {
      doc_id: "cloud-service-agreement",
      title: "Cloud Service Agreement (CSA)",
      standard_terms:
        'The <span class="coverpage_link">Customer</span> agrees under ' +
        '<span class="keyterms_link">Governing Law</span>.',
      cover_page: null,
      manifest: MANIFEST,
      ...overrides,
    },
  };
}

describe("GenericDocPreview with a manifest", () => {
  it("renders a structured cover page: filled, required-missing, optional", () => {
    render(
      <GenericDocPreview
        load={readyLoad()}
        fields={{ Customer: "Acme, Inc." }}
        locale="en"
      />,
    );
    expect(screen.getByText("Cover Page")).toBeInTheDocument();
    // Section headings from the manifest, localized.
    expect(screen.getByText("Parties")).toBeInTheDocument();
    // Filled value shown; required-missing flagged; optional shows a dash.
    expect(screen.getByText("Acme, Inc.")).toBeInTheDocument();
    expect(screen.getByText("[Not provided]")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("marks body term references as defined/missing", () => {
    const { container } = render(
      <GenericDocPreview
        load={readyLoad()}
        fields={{ Customer: "Acme, Inc." }}
        locale="en"
      />,
    );
    const defined = container.querySelector(".term-defined");
    expect(defined?.textContent).toBe("Customer");
    expect(defined?.getAttribute("title")).toBe("Customer: Acme, Inc.");
    const missing = container.querySelector(".term-missing");
    expect(missing?.textContent).toBe("Governing Law");
  });

  it("renders pending and conflict field state from draft_state", () => {
    const snapshot: DraftStateSnapshot = {
      schema_version: "draft-state.v1",
      manifest_version: 1,
      doc_id: "cloud-service-agreement",
      revision: 3,
      applied_patches: {},
      fields: {
        Customer: {
          key: "Customer",
          status: "conflict",
          value: "Acme, Inc.",
          revision: 3,
          confirmed_at: "2026-07-31T00:00:00+00:00",
          confirmed_by_user_id: 1,
          provenance: [],
          conflict: {
            base_value: "Acme, Inc.",
            proposed_value: "Beta LLC",
            provenance: {
              patch_id: "llm-2",
              source: "llm",
              operation: "propose",
              value: "Beta LLC",
            },
          },
        },
        "Governing Law": {
          key: "Governing Law",
          status: "pending_confirmation",
          value: "PRC law",
          revision: 2,
          provenance: [],
        },
      },
    };
    const { container } = render(
      <GenericDocPreview
        load={readyLoad()}
        fields={{}}
        draftState={snapshot}
        locale="en"
      />,
    );

    expect(screen.getByText("Conflict")).toBeInTheDocument();
    expect(screen.getByText("Current: Acme, Inc.")).toBeInTheDocument();
    expect(screen.getByText("Candidate: Beta LLC")).toBeInTheDocument();
    expect(screen.getByText("Pending confirmation")).toBeInTheDocument();
    expect(container.querySelector(".term-defined")?.textContent).toBe(
      "Customer",
    );
    expect(container.querySelector(".term-pending")?.textContent).toBe(
      "Governing Law",
    );
  });

  it("lists chat-collected terms the manifest doesn't declare", () => {
    render(
      <GenericDocPreview
        load={readyLoad()}
        fields={{ "Side Letter": "Attached as Exhibit A" }}
        locale="en"
      />,
    );
    expect(screen.getByText("Other terms")).toBeInTheDocument();
    expect(screen.getByText("Attached as Exhibit A")).toBeInTheDocument();
  });

  it("renders template cover_page markdown for manifest documents that have one", () => {
    const { container } = render(
      <GenericDocPreview
        load={readyLoad({
          cover_page:
            "# Template Cover Page\n\n" +
            '<span class="coverpage_link">Customer</span>',
        })}
        fields={{ Customer: "Acme, Inc." }}
        locale="en"
      />,
    );

    expect(screen.getByText("Template Cover Page")).toBeInTheDocument();
    const coverPageTerms = Array.from(
      container.querySelectorAll(".term-defined"),
    ).map((node) => node.textContent);
    expect(coverPageTerms).toContain("Customer");
  });

  it.each([
    ["confirmed", "Paid", true],
    ["confirmed", "Free", false],
    ["pending_confirmation", "Free", true],
  ] as const)(
    "renders conditional blocks for %s fields with value %s",
    (status, value, paidTermsVisible) => {
      const conditionalManifest: DocManifest = {
        ...MANIFEST,
        fields: [
          ...MANIFEST.fields,
          {
            key: "Pilot Pricing",
            section: "keyterms",
            type: "string",
            required: true,
            label: { zh: "试点收费方式", en: "Pilot pricing" },
          },
        ],
      };
      const snapshot: DraftStateSnapshot = {
        schema_version: "draft-state.v1",
        manifest_version: 1,
        doc_id: "cloud-service-agreement",
        revision: 1,
        applied_patches: {},
        fields: {
          "Pilot Pricing": {
            key: "Pilot Pricing",
            status,
            value,
            revision: 1,
            provenance: [],
            confirmed_at:
              status === "confirmed" ? "2026-08-06T00:00:00+00:00" : null,
            confirmed_by_user_id: status === "confirmed" ? 1 : null,
          },
        },
      };
      render(
        <GenericDocPreview
          load={readyLoad({
            manifest: conditionalManifest,
            standard_terms:
              '<!-- when {"field":"Pilot Pricing","op":"equals","value":"Paid"} -->\n' +
              "Paid-only payment and refund terms.\n" +
              "<!-- endwhen -->\n\nAlways-visible terms.",
          })}
          fields={{}}
          draftState={snapshot}
          locale="en"
        />,
      );

      expect(screen.getByText("Always-visible terms.")).toBeInTheDocument();
      const paidTerms = screen.queryByText("Paid-only payment and refund terms.");
      if (paidTermsVisible) expect(paidTerms).toBeInTheDocument();
      else expect(paidTerms).not.toBeInTheDocument();
    },
  );
});

describe("GenericDocPreview without a manifest", () => {
  it("falls back to the flat summary card and coming-soon note", () => {
    render(
      <GenericDocPreview
        load={readyLoad({ manifest: null, title: "Pilot Agreement" })}
        fields={{ Customer: "Acme" }}
        locale="en"
      />,
    );
    expect(screen.getByText("Cover Page Summary")).toBeInTheDocument();
    expect(screen.getByText(/coming soon/i)).toBeInTheDocument();
  });
});

describe("GenericDocPreview load states", () => {
  it("shows the error message when the template failed to load", () => {
    render(
      <GenericDocPreview
        load={{ kind: "error", message: "boom" }}
        fields={{}}
        locale="en"
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("boom");
  });
});
