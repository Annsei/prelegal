import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GenericDocPreview } from "./GenericDocPreview";
import type { TemplateResponse } from "@/lib/api";
import type { DocManifest } from "@/lib/docManifest";
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
