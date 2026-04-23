import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MNDAPreview } from "./MNDAPreview";
import { INITIAL_STATE, type MndaState } from "@/lib/mndaState";

function renderPreview(overrides: Partial<MndaState> = {}) {
  const state: MndaState = { ...INITIAL_STATE, ...overrides };
  return render(<MNDAPreview value={state} />);
}

describe("MNDAPreview", () => {
  it("renders the document header and attribution with upstream + license links", () => {
    renderPreview();
    expect(
      screen.getByRole("heading", {
        name: "Mutual Non-Disclosure Agreement",
        level: 1,
      }),
    ).toBeInTheDocument();
    const versionLink = screen.getByRole("link", { name: "Version 1.0" });
    expect(versionLink).toHaveAttribute(
      "href",
      "https://commonpaper.com/standards/mutual-nda/1.0/",
    );
    const licenseLink = screen.getByRole("link", { name: "CC BY 4.0" });
    expect(licenseLink).toHaveAttribute(
      "href",
      "https://creativecommons.org/licenses/by/4.0/",
    );
  });

  it("substitutes {{purpose}} in the Standard Terms body", () => {
    renderPreview({ purpose: "Evaluating a strategic partnership." });
    // The phrase should appear in the Standard Terms (at least twice, per
    // Introduction and Use and Protection sections).
    const matches = screen.getAllByText(/Evaluating a strategic partnership./);
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });

  it("substitutes {{governingLaw}} and {{jurisdiction}} in Section 9", () => {
    renderPreview({
      governingLaw: "California",
      jurisdiction: "courts located in San Francisco, CA",
    });
    // governingLaw appears twice in Section 9's body.
    expect(screen.getAllByText("California").length).toBeGreaterThanOrEqual(2);
    expect(
      screen.getAllByText("courts located in San Francisco, CA").length,
    ).toBeGreaterThanOrEqual(2);
  });

  it("reflects mndaTerm and confidentialityTerm in Section 5 body (regression)", () => {
    // Regression guard: Section 5 used to hard-code these strings. They must
    // follow the form state.
    renderPreview({
      mndaTermMode: "expires",
      mndaTermYears: 7,
      confidentialityMode: "perpetual",
    });
    // mndaTerm renders as "7 year(s) from the Effective Date"
    expect(
      screen.getByText(/7 year\(s\) from the Effective Date/),
    ).toBeInTheDocument();
    // confidentialityTerm renders as "in perpetuity"
    expect(screen.getByText(/in perpetuity/)).toBeInTheDocument();
  });

  it("renders formatted effectiveDate in both cover page and Section 5", () => {
    renderPreview({ effectiveDate: "2026-01-01" });
    // Cover-page header + Section 5 body each have their own rendering.
    const matches = screen.getAllByText("January 1, 2026");
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });

  it("renders confidentialityYears in the cover-page checklist", () => {
    renderPreview({
      confidentialityMode: "years",
      confidentialityYears: 12,
    });
    // Two "year(s)" occurrences in the cover page share the N year(s) shape;
    // one is MNDA Term, one is Term of Confidentiality. Verify the exact
    // match for 12 year(s) shows up at least once.
    expect(screen.getAllByText(/12 year\(s\)/).length).toBeGreaterThan(0);
  });

  it("emits .missing placeholders when party fields are empty", () => {
    // INITIAL_STATE leaves both parties blank; without any overrides, the 8
    // Party 1/2 fields alone must produce at least 8 missing pills.
    const { container } = renderPreview();
    const missingInTable = container.querySelectorAll(
      "table .missing",
    ).length;
    expect(missingInTable).toBeGreaterThanOrEqual(8);
  });

  it("emits no .missing pills in the signature table when both parties are fully filled", () => {
    const filled = {
      company: "Acme, Inc.",
      signerName: "Jane Doe",
      signerTitle: "CEO",
      noticeAddress: "jane@acme.com",
    };
    const { container } = renderPreview({
      party1: filled,
      party2: { ...filled, company: "Globex Corp." },
    });
    expect(
      container.querySelectorAll("table .missing").length,
    ).toBe(0);
  });

  it("shows filled party data in the signature table", () => {
    renderPreview({
      party1: {
        company: "Acme, Inc.",
        signerName: "Jane Doe",
        signerTitle: "CEO",
        noticeAddress: "jane@acme.com",
      },
    });
    expect(screen.getByText("Acme, Inc.")).toBeInTheDocument();
    expect(screen.getByText("Jane Doe")).toBeInTheDocument();
    expect(screen.getByText("CEO")).toBeInTheDocument();
    expect(screen.getByText("jane@acme.com")).toBeInTheDocument();
  });

  it("renders all 6 standard-row labels in the signature table", () => {
    renderPreview();
    const table = screen.getByRole("table");
    for (const label of [
      "Signature",
      "Print Name",
      "Title",
      "Company",
      "Notice Address",
      "Date",
    ]) {
      expect(within(table).getByText(label)).toBeInTheDocument();
    }
  });

  it("renders the Modifications cover-page field", () => {
    renderPreview({ modifications: "Section 5 shall not apply." });
    expect(
      screen.getByRole("heading", { name: "MNDA Modifications" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Section 5 shall not apply."),
    ).toBeInTheDocument();
  });

  it("tags the root article with data-print-root for print CSS", () => {
    const { container } = renderPreview();
    const printRoot = container.querySelector("[data-print-root]");
    expect(printRoot).not.toBeNull();
    expect(printRoot?.tagName.toLowerCase()).toBe("article");
  });

  it("renders Standard Terms heading and all 11 section headings", () => {
    renderPreview();
    expect(
      screen.getByRole("heading", { name: "Standard Terms", level: 2 }),
    ).toBeInTheDocument();
    // Each numbered list item's leading <strong> should carry the section name.
    for (const heading of [
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
    ]) {
      expect(screen.getByText(new RegExp(`^${heading}\\.`))).toBeInTheDocument();
    }
  });
});
