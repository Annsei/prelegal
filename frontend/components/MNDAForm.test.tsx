import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { MNDAForm } from "./MNDAForm";
import { INITIAL_STATE, type MndaState } from "@/lib/mndaState";
import type { Locale } from "@/lib/i18n";

function Harness({ initialLocale = "zh" as Locale }) {
  const [state, setState] = useState<MndaState>(INITIAL_STATE);
  return (
    <>
      <div data-testid="state-json">{JSON.stringify(state)}</div>
      <MNDAForm locale={initialLocale} value={state} onChange={setState} />
    </>
  );
}

function currentState(): MndaState {
  return JSON.parse(screen.getByTestId("state-json").textContent ?? "{}");
}

describe("MNDAForm", () => {
  it("renders Chinese labels when locale is zh", () => {
    render(<Harness initialLocale="zh" />);
    expect(screen.getByLabelText(/目的/)).toBeInTheDocument();
    expect(screen.getByLabelText(/生效日期/)).toBeInTheDocument();
  });

  it("renders English labels when locale is en", () => {
    render(<Harness initialLocale="en" />);
    expect(screen.getByLabelText(/Purpose/)).toBeInTheDocument();
    expect(screen.getByLabelText("Effective Date")).toBeInTheDocument();
  });

  it("updates state when user types into purpose", async () => {
    const user = userEvent.setup();
    render(<Harness initialLocale="en" />);
    const purpose = screen.getByLabelText(/Purpose/);
    await user.clear(purpose);
    await user.type(purpose, "Exploring an acquisition.");
    expect(currentState().purpose).toBe("Exploring an acquisition.");
  });

  it("toggles mndaTermMode via radio", async () => {
    const user = userEvent.setup();
    render(<Harness initialLocale="en" />);
    expect(currentState().mndaTermMode).toBe("expires");
    const continuesRadio = screen.getByLabelText(
      /Continues until terminated/,
    );
    await user.click(continuesRadio);
    expect(currentState().mndaTermMode).toBe("continues");
  });

  it("auto-selects 'expires' when user edits the year count (fix for radio/number desync)", async () => {
    const user = userEvent.setup();
    render(<Harness initialLocale="en" />);
    // Switch to continues first so `expires` is NOT selected.
    await user.click(screen.getByLabelText(/Continues until terminated/));
    expect(currentState().mndaTermMode).toBe("continues");

    // Now edit the number input — mode should flip to `expires`.
    const yearInputs = screen.getAllByRole("spinbutton");
    // First spinbutton corresponds to mnda term years.
    await user.clear(yearInputs[0]);
    await user.type(yearInputs[0], "3");
    const s = currentState();
    expect(s.mndaTermMode).toBe("expires");
    expect(s.mndaTermYears).toBe(3);
  });

  it("auto-selects 'years' when user edits confidentiality year count", async () => {
    const user = userEvent.setup();
    render(<Harness initialLocale="en" />);
    await user.click(screen.getByLabelText(/In perpetuity/));
    expect(currentState().confidentialityMode).toBe("perpetual");

    const yearInputs = screen.getAllByRole("spinbutton");
    // Second spinbutton corresponds to confidentiality years.
    await user.clear(yearInputs[1]);
    await user.type(yearInputs[1], "5");
    const s = currentState();
    expect(s.confidentialityMode).toBe("years");
    expect(s.confidentialityYears).toBe(5);
  });

  it("coerces negative year input to 0", () => {
    // Use fireEvent.change for a deterministic value round-trip; user.type
    // produces browser-specific sequences for minus/fractional keystrokes that
    // happy-dom doesn't fully emulate.
    render(<Harness initialLocale="en" />);
    const yearInput = screen.getAllByRole("spinbutton")[0];
    fireEvent.change(yearInput, { target: { value: "-5" } });
    expect(currentState().mndaTermYears).toBe(0);
  });

  it("coerces empty year input to 0", () => {
    render(<Harness initialLocale="en" />);
    const yearInput = screen.getAllByRole("spinbutton")[0];
    fireEvent.change(yearInput, { target: { value: "" } });
    expect(currentState().mndaTermYears).toBe(0);
  });

  it("updates party1 and party2 independently", async () => {
    const user = userEvent.setup();
    render(<Harness initialLocale="en" />);
    const p1Company = screen.getByLabelText(/Company/, { selector: "#party1-company" });
    const p2Company = screen.getByLabelText(/Company/, { selector: "#party2-company" });
    await user.type(p1Company, "Acme, Inc.");
    await user.type(p2Company, "Globex Corp.");
    const s = currentState();
    expect(s.party1.company).toBe("Acme, Inc.");
    expect(s.party2.company).toBe("Globex Corp.");
  });

  it("exposes the Modifications field (regression: was missing from v1)", () => {
    render(<Harness initialLocale="en" />);
    expect(
      screen.getByLabelText(/Modifications to Standard Terms/),
    ).toBeInTheDocument();
  });
});
