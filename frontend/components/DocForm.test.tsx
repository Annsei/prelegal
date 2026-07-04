import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DocForm } from "./DocForm";
import type { DocManifest } from "@/lib/docManifest";

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
      label: { zh: "费用", en: "Fees" },
    },
  ],
};

describe("DocForm", () => {
  it("renders sections, labels, required marks, hints, and examples", () => {
    render(
      <DocForm locale="en" manifest={MANIFEST} values={{}} onChange={() => {}} />,
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
    expect(screen.getAllByText("*required")).toHaveLength(2);
  });

  it("shows current values and emits per-key changes", async () => {
    const onChange = vi.fn();
    render(
      <DocForm
        locale="en"
        manifest={MANIFEST}
        values={{ Customer: "Acme" }}
        onChange={onChange}
      />,
    );
    const customer = screen.getByLabelText(/Customer \(company\)/);
    expect(customer).toHaveValue("Acme");
    await userEvent.type(customer, "!");
    expect(onChange).toHaveBeenLastCalledWith("Customer", "Acme!");
  });

  it("renders localized labels in Chinese", () => {
    render(
      <DocForm locale="zh" manifest={MANIFEST} values={{}} onChange={() => {}} />,
    );
    expect(screen.getByText("当事方")).toBeInTheDocument();
    expect(screen.getByLabelText(/客户/)).toBeInTheDocument();
  });
});
