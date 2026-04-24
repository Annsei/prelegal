import type { MndaState, PartyInfo } from "@/lib/mndaState";
import { formatEffectiveDate } from "@/lib/mndaState";
import {
  ATTRIBUTION_LICENSE_URL,
  ATTRIBUTION_VERSION_URL,
  type PlaceholderKey,
  STANDARD_TERMS_SECTIONS,
  parseSegments,
} from "@/lib/mndaTemplate";

type Props = { value: MndaState };

// The Common Paper template is English-only; translating it would alter its legal meaning.
export function MNDAPreview({ value }: Props) {
  const lookup = buildPlaceholderLookup(value);
  return (
    <article data-print-root className="doc bg-white px-10 py-12 shadow-sm">
      <CoverPage value={value} lookup={lookup} />
      <div className="mt-10 border-t border-neutral-300 pt-6">
        <StandardTerms lookup={lookup} />
      </div>
      <p className="mt-8 text-xs italic text-neutral-600">
        Common Paper Mutual Non-Disclosure Agreement{" "}
        <a href={ATTRIBUTION_VERSION_URL} className="underline">
          Version 1.0
        </a>{" "}
        free to use under{" "}
        <a href={ATTRIBUTION_LICENSE_URL} className="underline">
          CC BY 4.0
        </a>
        .
      </p>
    </article>
  );
}

type Lookup = Record<PlaceholderKey, string>;

function buildPlaceholderLookup(v: MndaState): Lookup {
  const mndaTerm =
    v.mndaTermMode === "expires"
      ? `${v.mndaTermYears} year(s) from the Effective Date`
      : "term until terminated";
  const confidentialityTerm =
    v.confidentialityMode === "years"
      ? `${v.confidentialityYears} year(s) from the Effective Date`
      : "in perpetuity";
  return {
    purpose: v.purpose,
    governingLaw: v.governingLaw,
    jurisdiction: v.jurisdiction,
    effectiveDate: formatEffectiveDate(v.effectiveDate),
    mndaTerm,
    confidentialityTerm,
  };
}

function CoverPage({ value, lookup }: { value: MndaState; lookup: Lookup }) {
  return (
    <section>
      <h1>Mutual Non-Disclosure Agreement</h1>

      <h3>Purpose</h3>
      <p>
        <Filled value={lookup.purpose} placeholder="[Purpose]" />
      </p>

      <h3>Effective Date</h3>
      <p>
        <Filled value={lookup.effectiveDate} placeholder="[Effective Date]" />
      </p>

      <h3>MNDA Term</h3>
      <ul className="list-none pl-0">
        <li>
          <Checkbox checked={value.mndaTermMode === "expires"} /> Expires{" "}
          <Filled
            value={
              value.mndaTermMode === "expires"
                ? `${value.mndaTermYears} year(s)`
                : ""
            }
            placeholder="[N year(s)]"
          />{" "}
          from Effective Date.
        </li>
        <li>
          <Checkbox checked={value.mndaTermMode === "continues"} /> Continues
          until terminated in accordance with the terms of the MNDA.
        </li>
      </ul>

      <h3>Term of Confidentiality</h3>
      <ul className="list-none pl-0">
        <li>
          <Checkbox checked={value.confidentialityMode === "years"} />{" "}
          <Filled
            value={
              value.confidentialityMode === "years"
                ? `${value.confidentialityYears} year(s)`
                : ""
            }
            placeholder="[N year(s)]"
          />{" "}
          from Effective Date, but in the case of trade secrets until
          Confidential Information is no longer considered a trade secret under
          applicable laws.
        </li>
        <li>
          <Checkbox checked={value.confidentialityMode === "perpetual"} /> In
          perpetuity.
        </li>
      </ul>

      <h3>Governing Law &amp; Jurisdiction</h3>
      <p>
        Governing Law:{" "}
        <Filled value={lookup.governingLaw} placeholder="[Fill in state]" />
      </p>
      <p>
        Jurisdiction:{" "}
        <Filled
          value={lookup.jurisdiction}
          placeholder="[Fill in city or county and state]"
        />
      </p>

      <h3>MNDA Modifications</h3>
      <p>
        <Filled
          value={value.modifications}
          placeholder="[None — list any modifications to the MNDA]"
        />
      </p>

      <p className="mt-6">
        By signing this Cover Page, each party agrees to enter into this MNDA as
        of the Effective Date.
      </p>

      <SignatureTable value={value} />
    </section>
  );
}

const SIGNATURE_ROWS: { label: string; key?: keyof PartyInfo }[] = [
  { label: "Signature" },
  { label: "Print Name", key: "signerName" },
  { label: "Title", key: "signerTitle" },
  { label: "Company", key: "company" },
  { label: "Notice Address", key: "noticeAddress" },
  { label: "Date" },
];

const PARTIES = ["party1", "party2"] as const;

function SignatureTable({ value }: { value: MndaState }) {
  return (
    <table>
      <thead>
        <tr>
          <th></th>
          <th>Party 1</th>
          <th>Party 2</th>
        </tr>
      </thead>
      <tbody>
        {SIGNATURE_ROWS.map(({ label, key }) => (
          <tr key={label}>
            <th>{label}</th>
            {PARTIES.map((p) => (
              <td key={p}>
                {key ? <Filled value={value[p][key]} placeholder="" /> : <>&nbsp;</>}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function StandardTerms({ lookup }: { lookup: Lookup }) {
  return (
    <section>
      <h2>Standard Terms</h2>
      <ol>
        {STANDARD_TERMS_SECTIONS.map((section) => (
          <li key={section.heading}>
            <strong>{section.heading}.</strong>{" "}
            {parseSegments(section.body).map((seg, i) => {
              if (seg.type === "text") return <span key={i}>{seg.value}</span>;
              if (seg.type === "bold")
                return <strong key={i}>{seg.value}</strong>;
              return (
                <Filled
                  key={i}
                  value={lookup[seg.key]}
                  placeholder={`[${seg.key}]`}
                />
              );
            })}
          </li>
        ))}
      </ol>
    </section>
  );
}

function Filled({
  value,
  placeholder,
}: {
  value: string;
  placeholder: string;
}) {
  const trimmed = value.trim();
  if (!trimmed) {
    return <span className="missing">{placeholder || "[—]"}</span>;
  }
  return <span className="filled">{trimmed}</span>;
}

function Checkbox({ checked }: { checked: boolean }) {
  return (
    <span
      aria-hidden
      className="mr-1 inline-block h-3 w-3 border border-neutral-500 align-middle"
      style={{ background: checked ? "#111" : "transparent" }}
    />
  );
}
