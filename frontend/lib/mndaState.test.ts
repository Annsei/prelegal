import { describe, expect, it } from "vitest";
import {
  formatEffectiveDate,
  INITIAL_STATE,
  type MndaState,
} from "./mndaState";

describe("formatEffectiveDate", () => {
  it("formats an ISO date in US long-month form", () => {
    expect(formatEffectiveDate("2026-04-23")).toBe("April 23, 2026");
  });

  it("returns the date that was selected, not the prior day (UTC parse guard)", () => {
    // Regression: `new Date("2026-01-01")` is midnight UTC, which renders as
    // Dec 31, 2025 in any west-of-UTC timezone. parseInt-split logic must keep
    // this deterministic regardless of TZ.
    expect(formatEffectiveDate("2026-01-01")).toBe("January 1, 2026");
    expect(formatEffectiveDate("2026-12-31")).toBe("December 31, 2026");
  });

  it("returns empty string for empty input", () => {
    expect(formatEffectiveDate("")).toBe("");
  });

  it("passes through malformed input unchanged", () => {
    expect(formatEffectiveDate("not-a-date")).toBe("not-a-date");
    expect(formatEffectiveDate("2026-13")).toBe("2026-13");
  });
});

describe("INITIAL_STATE", () => {
  it("uses today's calendar date in the local timezone", () => {
    const today = new Date();
    const expected = [
      today.getFullYear(),
      String(today.getMonth() + 1).padStart(2, "0"),
      String(today.getDate()).padStart(2, "0"),
    ].join("-");
    expect(INITIAL_STATE.effectiveDate).toBe(expected);
  });

  it("includes every required top-level field", () => {
    const keys: (keyof MndaState)[] = [
      "purpose",
      "effectiveDate",
      "mndaTermMode",
      "mndaTermYears",
      "confidentialityMode",
      "confidentialityYears",
      "governingLaw",
      "jurisdiction",
      "modifications",
      "party1",
      "party2",
    ];
    for (const key of keys) {
      expect(INITIAL_STATE).toHaveProperty(key);
    }
  });

  it("defaults both parties to empty-field structs", () => {
    for (const party of [INITIAL_STATE.party1, INITIAL_STATE.party2]) {
      expect(party).toEqual({
        company: "",
        signerName: "",
        signerTitle: "",
        noticeAddress: "",
      });
    }
  });
});
