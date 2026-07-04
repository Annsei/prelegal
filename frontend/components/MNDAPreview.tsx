import type { MndaState, PartyInfo } from "@/lib/mndaState";
import { formatEffectiveDate } from "@/lib/mndaState";
import {
  type PlaceholderKey,
  STANDARD_TERMS_SECTIONS,
  TEMPLATE_NOTICE,
  TEMPLATE_VERSION_LABEL,
  parseSegments,
} from "@/lib/mndaTemplate";

type Props = { value: MndaState };

// 中国法《双方保密协议》范本（Prelegal v1.0）——合同正文为简体中文；
// 界面语言切换只影响 UI chrome，不改变合同文本。
export function MNDAPreview({ value }: Props) {
  const lookup = buildPlaceholderLookup(value);
  return (
    <article
      data-print-root
      className="card doc px-10 py-12"
      style={{ borderTop: "3px solid var(--ink)" }}
    >
      <CoverPage value={value} lookup={lookup} />
      <div className="mt-10 border-t border-neutral-300 pt-6">
        <StandardTerms lookup={lookup} />
      </div>
      <p className="mt-8 text-xs italic text-neutral-600">
        {TEMPLATE_VERSION_LABEL} · {TEMPLATE_NOTICE}
      </p>
    </article>
  );
}

type Lookup = Record<PlaceholderKey, string>;

function buildPlaceholderLookup(v: MndaState): Lookup {
  const mndaTerm =
    v.mndaTermMode === "expires"
      ? `自生效日期起 ${v.mndaTermYears} 年`
      : "持续有效，直至依约终止";
  const confidentialityTerm =
    v.confidentialityMode === "years"
      ? `自生效日期起 ${v.confidentialityYears} 年`
      : "永久";
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
      <h1>双方保密协议</h1>

      <h3>保密用途</h3>
      <p>
        <Filled value={lookup.purpose} placeholder="[保密用途]" />
      </p>

      <h3>生效日期</h3>
      <p>
        <Filled value={lookup.effectiveDate} placeholder="[生效日期]" />
      </p>

      <h3>协议期限</h3>
      <ul className="list-none pl-0">
        <li>
          <Checkbox checked={value.mndaTermMode === "expires"} /> 自生效日期起{" "}
          <Filled
            value={
              value.mndaTermMode === "expires"
                ? `${value.mndaTermYears} 年`
                : ""
            }
            placeholder="[N 年]"
          />{" "}
          届满时到期。
        </li>
        <li>
          <Checkbox checked={value.mndaTermMode === "continues"} />{" "}
          持续有效，直至依本协议约定终止。
        </li>
      </ul>

      <h3>保密期限</h3>
      <ul className="list-none pl-0">
        <li>
          <Checkbox checked={value.confidentialityMode === "years"} /> 自生效日期起{" "}
          <Filled
            value={
              value.confidentialityMode === "years"
                ? `${value.confidentialityYears} 年`
                : ""
            }
            placeholder="[N 年]"
          />
          ；构成商业秘密的信息，至其依法不再构成商业秘密时止。
        </li>
        <li>
          <Checkbox checked={value.confidentialityMode === "perpetual"} /> 永久。
        </li>
      </ul>

      <h3>适用法律与争议解决</h3>
      <p>
        适用法律：{" "}
        <Filled
          value={lookup.governingLaw}
          placeholder="[默认：中华人民共和国法律]"
        />
      </p>
      <p>
        争议解决：{" "}
        <Filled
          value={lookup.jurisdiction}
          placeholder="[填写仲裁机构或管辖法院]"
        />
      </p>

      <h3>对标准条款的修订</h3>
      <p>
        <Filled
          value={value.modifications}
          placeholder="[无——如需修订标准条款请在此列明]"
        />
      </p>

      <p className="mt-6">双方签署本封面页，即同意自生效日期起订立本协议。</p>

      <SignatureTable value={value} />
    </section>
  );
}

const SIGNATURE_ROWS: { label: string; key?: keyof PartyInfo }[] = [
  { label: "签字" },
  { label: "姓名", key: "signerName" },
  { label: "职务", key: "signerTitle" },
  { label: "公司名称", key: "company" },
  { label: "通知地址", key: "noticeAddress" },
  { label: "签署日期" },
];

const PARTIES = ["party1", "party2"] as const;

function SignatureTable({ value }: { value: MndaState }) {
  return (
    <table>
      <thead>
        <tr>
          <th></th>
          <th>甲方</th>
          <th>乙方</th>
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

const PLACEHOLDER_LABELS: Record<PlaceholderKey, string> = {
  purpose: "保密用途",
  governingLaw: "适用法律",
  jurisdiction: "争议解决",
  effectiveDate: "生效日期",
  mndaTerm: "协议期限",
  confidentialityTerm: "保密期限",
};

function StandardTerms({ lookup }: { lookup: Lookup }) {
  return (
    <section>
      <h2>标准条款</h2>
      <ol>
        {STANDARD_TERMS_SECTIONS.map((section) => (
          <li key={section.heading}>
            <strong>{section.heading}。</strong>
            {parseSegments(section.body).map((seg, i) => {
              if (seg.type === "text") return <span key={i}>{seg.value}</span>;
              if (seg.type === "bold")
                return <strong key={i}>{seg.value}</strong>;
              return (
                <Filled
                  key={i}
                  value={lookup[seg.key]}
                  placeholder={`[${PLACEHOLDER_LABELS[seg.key]}]`}
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
