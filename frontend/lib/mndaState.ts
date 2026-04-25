export type PartyInfo = {
  company: string;
  signerName: string;
  signerTitle: string;
  noticeAddress: string;
};

export type MndaTermMode = "expires" | "continues";
export type ConfidentialityMode = "years" | "perpetual";

export type MndaState = {
  purpose: string;
  effectiveDate: string;
  mndaTermMode: MndaTermMode;
  mndaTermYears: number;
  confidentialityMode: ConfidentialityMode;
  confidentialityYears: number;
  governingLaw: string;
  jurisdiction: string;
  modifications: string;
  party1: PartyInfo;
  party2: PartyInfo;
};

function todayLocalISO(): string {
  // Same local-calendar construction `formatEffectiveDate` relies on —
  // `new Date().toISOString()` would be UTC and render as yesterday in any
  // west-of-UTC timezone after local midnight minus the offset.
  const d = new Date();
  return [
    d.getFullYear(),
    String(d.getMonth() + 1).padStart(2, "0"),
    String(d.getDate()).padStart(2, "0"),
  ].join("-");
}

export const INITIAL_STATE: MndaState = {
  purpose: "Evaluating whether to enter into a business relationship with the other party.",
  effectiveDate: todayLocalISO(),
  mndaTermMode: "expires",
  mndaTermYears: 1,
  confidentialityMode: "years",
  confidentialityYears: 1,
  governingLaw: "Delaware",
  jurisdiction: "courts located in New Castle, DE",
  modifications: "",
  party1: {
    company: "",
    signerName: "",
    signerTitle: "",
    noticeAddress: "",
  },
  party2: {
    company: "",
    signerName: "",
    signerTitle: "",
    noticeAddress: "",
  },
};

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value)
  );
}

/**
 * Merge a partial update from the AI into the current state.
 *
 * Unknown keys are dropped (the AI's structured output schema constrains the
 * shape, but we still defend the client). PartyInfo updates are merged
 * field-by-field so a turn that only learns party1.company doesn't blow away
 * party1.signerName. Allowed keys are derived from the live `current` object
 * — there is no parallel allowlist that could drift from the type.
 */
export function mergeMndaUpdates(
  current: MndaState,
  updates: Record<string, unknown>,
): MndaState {
  const next: MndaState = { ...current };
  for (const [rawKey, value] of Object.entries(updates)) {
    if (rawKey === "__proto__" || rawKey === "constructor") continue;
    if (!Object.prototype.hasOwnProperty.call(current, rawKey)) continue;
    const key = rawKey as keyof MndaState;
    const currentValue = current[key];

    if (isPlainObject(currentValue)) {
      // Party fields: deep-merge.
      if (!isPlainObject(value)) continue;
      const merged: PartyInfo = { ...currentValue } as PartyInfo;
      for (const [fk, fv] of Object.entries(value)) {
        if (
          fk in merged &&
          typeof fv === "string" &&
          fk !== "__proto__"
        ) {
          (merged as Record<string, string>)[fk] = fv;
        }
      }
      (next as Record<string, unknown>)[key] = merged;
      continue;
    }

    // Top-level scalars — accept the value only if its runtime type matches
    // the existing state's.
    if (typeof value === typeof currentValue) {
      (next as Record<string, unknown>)[key] = value;
    }
  }
  return next;
}

export function formatEffectiveDate(iso: string): string {
  if (!iso) return "";
  // Parse as a local calendar date — `new Date("2026-04-23")` would be midnight
  // UTC, which renders as the previous day in negative timezones.
  const [y, m, d] = iso.split("-").map((n) => parseInt(n, 10));
  if (!y || !m || !d) return iso;
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}
