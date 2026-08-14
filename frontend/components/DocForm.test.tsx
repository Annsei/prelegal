import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DocForm } from "./DocForm";
import type { DocManifest } from "@/lib/docManifest";
import type {
  DraftFieldState,
  DraftStateSnapshot,
} from "@/lib/draftState";

const MANIFEST: DocManifest = {
  doc_id: "cloud-service-agreement",
  version: 1,
  sections: [
    { key: "parties", label: { zh: "当事方", en: "Parties" } },
    { key: "order", label: { zh: "订单条款", en: "Order Form" } },
  ],
  fields: [
    {
      key: "Customer",
      section: "parties",
      type: "string",
      required: true,
      label: { zh: "客户", en: "Customer (company)" },
      hint: { zh: "订阅方", en: "The subscribing party" },
      example: "Acme, Inc.",
    },
    {
      key: "Order Date",
      section: "order",
      type: "date",
      required: true,
      label: { zh: "订单日期", en: "Order Date" },
    },
    {
      key: "Fees",
      section: "order",
      type: "text",
      required: false,
      required_when: {
        field: "Pricing Model",
        op: "equals",
        value: "付费",
      },
      label: { zh: "费用", en: "Fees" },
    },
    {
      key: "Pricing Model",
      section: "order",
      type: "string",
      required: true,
      enum: ["免费", "付费"],
      label: { zh: "收费方式", en: "Pricing Model" },
    },
  ],
};

describe("DocForm", () => {
  it("renders sections, labels, required marks, hints, and examples", () => {
    render(
      <DocForm
        locale="en"
        manifest={MANIFEST}
        values={{}}
        onConfirm={() => {}}
      />,
    );
    expect(screen.getByText("Parties")).toBeInTheDocument();
    expect(screen.getByText("Order Form")).toBeInTheDocument();
    const customer = screen.getByLabelText(/Customer \(company\)/);
    expect(customer).toHaveAttribute("placeholder", "Acme, Inc.");
    expect(screen.getByText("The subscribing party")).toBeInTheDocument();
    // Date fields render native date inputs; long-text fields a textarea.
    expect(screen.getByLabelText(/Order Date/)).toHaveAttribute("type", "date");
    expect(screen.getByLabelText(/Fees/).tagName).toBe("TEXTAREA");
    // Required mark on required fields only.
    expect(screen.getAllByText("*required")).toHaveLength(3);
  });

  it("marks conditionally required fields from confirmed stable values", () => {
    const snapshot = (pricing: string): DraftStateSnapshot => ({
      schema_version: "draft-state.v1",
      manifest_version: 1,
      doc_id: MANIFEST.doc_id,
      revision: 1,
      applied_patches: {},
      fields: {
        "Pricing Model": {
          key: "Pricing Model",
          status: "confirmed",
          value: pricing,
          revision: 1,
          provenance: [],
          confirmed_at: "2026-08-14T00:00:00+00:00",
          confirmed_by_user_id: 1,
        },
      },
    });
    const { rerender } = render(
      <DocForm
        locale="en"
        manifest={MANIFEST}
        values={{}}
        draftState={snapshot("付费")}
        onConfirm={() => {}}
      />,
    );

    const paidFees = screen.getByLabelText(/Fees/);
    expect(paidFees.labels?.[0]).toHaveTextContent("*required");

    rerender(
      <DocForm
        locale="en"
        manifest={MANIFEST}
        values={{}}
        draftState={snapshot("免费")}
        onConfirm={() => {}}
      />,
    );
    const freeFees = screen.getByLabelText(/Fees/);
    expect(freeFees.labels?.[0]).not.toHaveTextContent("*required");
  });

  it("shows current values and confirms only after an explicit action", async () => {
    const onConfirm = vi.fn();
    render(
      <DocForm
        locale="en"
        manifest={MANIFEST}
        values={{ Customer: "Acme" }}
        onConfirm={onConfirm}
      />,
    );
    const customer = screen.getByLabelText(/Customer \(company\)/);
    expect(customer).toHaveValue("Acme");
    await userEvent.type(customer, "!");
    expect(onConfirm).not.toHaveBeenCalled();
    await userEvent.click(screen.getAllByRole("button", { name: "Confirm" })[0]);
    expect(onConfirm).toHaveBeenLastCalledWith("Customer", "Acme!");
  });

  it("disables confirm for empty missing fields before sending a doomed patch", () => {
    const onConfirm = vi.fn();
    render(
      <DocForm
        locale="en"
        manifest={MANIFEST}
        values={{}}
        onConfirm={onConfirm}
      />,
    );

    const confirm = screen.getAllByRole("button", { name: "Confirm" })[0];
    expect(confirm).toBeDisabled();
    expect(confirm).toHaveAttribute(
      "title",
      "Enter a value before confirming a missing field.",
    );
    expect(confirm).toHaveAccessibleDescription(
      "Enter a value before confirming a missing field.",
    );
  });

  it("keeps explicit clear-and-confirm available for fields that already exist", async () => {
    const onConfirm = vi.fn();
    const fieldStates: Record<string, DraftFieldState> = {
      Customer: {
        key: "Customer",
        status: "confirmed",
        value: "Acme",
        revision: 1,
        provenance: [],
        confirmed_at: "2026-07-31T00:00:00+00:00",
        confirmed_by_user_id: 1,
      },
    };
    render(
      <DocForm
        locale="en"
        manifest={MANIFEST}
        values={{ Customer: "Acme" }}
        fieldStates={fieldStates}
        onConfirm={onConfirm}
      />,
    );

    const customer = screen.getByLabelText(/Customer \(company\)/);
    await userEvent.clear(customer);
    const confirm = screen.getAllByRole("button", { name: "Confirm" })[0];
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledWith("Customer", "");
  });

  it("shows pending and conflict states with confirm/reject actions", async () => {
    const onConfirm = vi.fn();
    const onReject = vi.fn();
    const fieldStates: Record<string, DraftFieldState> = {
      Customer: {
        key: "Customer",
        status: "conflict",
        value: "Acme",
        revision: 3,
        confirmed_at: "2026-07-31T00:00:00+00:00",
        confirmed_by_user_id: 1,
        provenance: [],
        conflict: {
          base_value: "Acme",
          proposed_value: "Beta",
          provenance: {
            patch_id: "llm-2",
            source: "llm",
            operation: "propose",
            value: "Beta",
          },
        },
      },
      "Order Date": {
        key: "Order Date",
        status: "pending_confirmation",
        value: "2026-07-01",
        revision: 2,
        provenance: [],
      },
    };
    render(
      <DocForm
        locale="en"
        manifest={MANIFEST}
        values={{}}
        fieldStates={fieldStates}
        onConfirm={onConfirm}
        onReject={onReject}
      />,
    );

    expect(screen.getByText("Conflict")).toBeInTheDocument();
    expect(screen.getByText("Current: Acme")).toBeInTheDocument();
    expect(screen.getByText("Candidate: Beta")).toBeInTheDocument();
    expect(screen.getByText("Pending confirmation")).toBeInTheDocument();
    expect(screen.getAllByText("Missing")).toHaveLength(2);
    expect(document.querySelector('[data-field-status="conflict"]')).toBeTruthy();
    expect(
      document.querySelector('[data-field-status="pending_confirmation"]'),
    ).toBeTruthy();
    expect(document.querySelector('[data-field-status="missing"]')).toBeTruthy();

    await userEvent.click(screen.getAllByRole("button", { name: "Confirm" })[0]);
    expect(onConfirm).toHaveBeenCalledWith("Customer", "Beta");
    await userEvent.click(screen.getAllByRole("button", { name: "Reject" })[0]);
    expect(onReject).toHaveBeenCalledWith("Customer");
  });

  it("renders localized labels in Chinese", () => {
    render(
      <DocForm
        locale="zh"
        manifest={MANIFEST}
        values={{}}
        onConfirm={() => {}}
      />,
    );
    expect(screen.getByText("当事方")).toBeInTheDocument();
    expect(screen.getByLabelText(/客户/)).toBeInTheDocument();
  });

  it("renders manifest enum fields as constrained selects", async () => {
    const onConfirm = vi.fn();
    render(
      <DocForm
        locale="en"
        manifest={MANIFEST}
        values={{}}
        onConfirm={onConfirm}
      />,
    );

    const pricing = screen.getByRole("combobox", { name: /Pricing Model/ });
    expect(pricing).toHaveValue("");
    expect(screen.getByRole("option", { name: "免费" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "付费" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /Pricing Model/ })).toBeNull();

    await userEvent.selectOptions(pricing, "付费");
    const field = pricing.closest(".doc-field");
    expect(field).not.toBeNull();
    await userEvent.click(
      Array.from(field!.querySelectorAll("button")).find(
        (button) => button.textContent === "Confirm",
      )!,
    );
    expect(onConfirm).toHaveBeenCalledWith("Pricing Model", "付费");
  });
});
