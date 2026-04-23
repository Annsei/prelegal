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
