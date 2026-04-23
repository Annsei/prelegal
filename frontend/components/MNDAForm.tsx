"use client";

import type { ChangeEvent } from "react";
import type { Locale } from "@/lib/i18n";
import { useDictionary } from "@/lib/i18n";
import type { MndaState, PartyInfo } from "@/lib/mndaState";

type Props = {
  locale: Locale;
  value: MndaState;
  onChange: (next: MndaState) => void;
};

type PartyKey = "party1" | "party2";

export function MNDAForm({ locale, value, onChange }: Props) {
  const t = useDictionary(locale);

  const setField = <K extends keyof MndaState>(key: K, v: MndaState[K]) =>
    onChange({ ...value, [key]: v });

  const setPartyField = (party: PartyKey, key: keyof PartyInfo, v: string) =>
    onChange({ ...value, [party]: { ...value[party], [key]: v } });

  return (
    <form className="space-y-6" onSubmit={(e) => e.preventDefault()}>
      <Section title={t.sections.agreement}>
        <Field
          label={t.labels.purpose}
          help={t.labels.purposeHelp}
          htmlFor="purpose"
        >
          <textarea
            id="purpose"
            className={textareaCls}
            rows={2}
            placeholder={t.placeholders.purpose}
            value={value.purpose}
            onChange={(e) => setField("purpose", e.target.value)}
          />
        </Field>
      </Section>

      <Section title={t.sections.dates}>
        <Field label={t.labels.effectiveDate} htmlFor="effectiveDate">
          <input
            id="effectiveDate"
            type="date"
            className={inputCls}
            value={value.effectiveDate}
            onChange={(e) => setField("effectiveDate", e.target.value)}
          />
        </Field>

        <Field label={t.labels.mndaTerm}>
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="mndaTermMode"
                checked={value.mndaTermMode === "expires"}
                onChange={() => setField("mndaTermMode", "expires")}
              />
              <span>{t.labels.mndaTermExpires}</span>
              <input
                type="number"
                min={0}
                className={numberCls}
                value={value.mndaTermYears}
                onChange={(e) =>
                  onChange({
                    ...value,
                    mndaTermMode: "expires",
                    mndaTermYears: toNonNegInt(e),
                  })
                }
              />
              <span>{t.labels.mndaTermYears}</span>
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="mndaTermMode"
                checked={value.mndaTermMode === "continues"}
                onChange={() => setField("mndaTermMode", "continues")}
              />
              <span>{t.labels.mndaTermContinues}</span>
            </label>
          </div>
        </Field>

        <Field label={t.labels.confidentialityTerm}>
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="confidentialityMode"
                checked={value.confidentialityMode === "years"}
                onChange={() => setField("confidentialityMode", "years")}
              />
              <input
                type="number"
                min={0}
                className={numberCls}
                value={value.confidentialityYears}
                onChange={(e) =>
                  onChange({
                    ...value,
                    confidentialityMode: "years",
                    confidentialityYears: toNonNegInt(e),
                  })
                }
              />
              <span>{t.labels.confidentialityYears}</span>
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="confidentialityMode"
                checked={value.confidentialityMode === "perpetual"}
                onChange={() => setField("confidentialityMode", "perpetual")}
              />
              <span>{t.labels.confidentialityPerpetual}</span>
            </label>
          </div>
        </Field>
      </Section>

      <Section title={t.sections.governing}>
        <Field
          label={t.labels.governingLaw}
          help={t.labels.governingLawHelp}
          htmlFor="governingLaw"
        >
          <input
            id="governingLaw"
            className={inputCls}
            placeholder={t.placeholders.governingLaw}
            value={value.governingLaw}
            onChange={(e) => setField("governingLaw", e.target.value)}
          />
        </Field>
        <Field
          label={t.labels.jurisdiction}
          help={t.labels.jurisdictionHelp}
          htmlFor="jurisdiction"
        >
          <input
            id="jurisdiction"
            className={inputCls}
            placeholder={t.placeholders.jurisdiction}
            value={value.jurisdiction}
            onChange={(e) => setField("jurisdiction", e.target.value)}
          />
        </Field>
      </Section>

      <Section title={t.sections.modifications}>
        <Field
          label={t.labels.modifications}
          help={t.labels.modificationsHelp}
          htmlFor="modifications"
        >
          <textarea
            id="modifications"
            className={textareaCls}
            rows={2}
            value={value.modifications}
            onChange={(e) => setField("modifications", e.target.value)}
          />
        </Field>
      </Section>

      <Section title={t.sections.parties}>
        <PartyBlock
          locale={locale}
          label={t.labels.party1}
          value={value.party1}
          onChange={(k, v) => setPartyField("party1", k, v)}
          idPrefix="party1"
        />
        <PartyBlock
          locale={locale}
          label={t.labels.party2}
          value={value.party2}
          onChange={(k, v) => setPartyField("party2", k, v)}
          idPrefix="party2"
        />
      </Section>
    </form>
  );
}

function PartyBlock({
  locale,
  label,
  value,
  onChange,
  idPrefix,
}: {
  locale: Locale;
  label: string;
  value: PartyInfo;
  onChange: (key: keyof PartyInfo, v: string) => void;
  idPrefix: string;
}) {
  const t = useDictionary(locale);
  return (
    <div className="rounded-md border border-neutral-200 bg-white/40 p-3">
      <h4 className="mb-2 text-sm font-semibold text-neutral-800">{label}</h4>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Field label={t.labels.company} htmlFor={`${idPrefix}-company`}>
          <input
            id={`${idPrefix}-company`}
            className={inputCls}
            placeholder={t.placeholders.company}
            value={value.company}
            onChange={(e) => onChange("company", e.target.value)}
          />
        </Field>
        <Field label={t.labels.signerName} htmlFor={`${idPrefix}-signerName`}>
          <input
            id={`${idPrefix}-signerName`}
            className={inputCls}
            placeholder={t.placeholders.signerName}
            value={value.signerName}
            onChange={(e) => onChange("signerName", e.target.value)}
          />
        </Field>
        <Field label={t.labels.signerTitle} htmlFor={`${idPrefix}-signerTitle`}>
          <input
            id={`${idPrefix}-signerTitle`}
            className={inputCls}
            placeholder={t.placeholders.signerTitle}
            value={value.signerTitle}
            onChange={(e) => onChange("signerTitle", e.target.value)}
          />
        </Field>
        <Field
          label={t.labels.noticeAddress}
          help={t.labels.noticeAddressHelp}
          htmlFor={`${idPrefix}-noticeAddress`}
        >
          <input
            id={`${idPrefix}-noticeAddress`}
            className={inputCls}
            placeholder={t.placeholders.noticeAddress}
            value={value.noticeAddress}
            onChange={(e) => onChange("noticeAddress", e.target.value)}
          />
        </Field>
      </div>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h3 className="mb-3 border-b border-neutral-200 pb-1 text-xs font-semibold uppercase tracking-wider text-neutral-500">
        {title}
      </h3>
      <div className="space-y-4">{children}</div>
    </section>
  );
}

function Field({
  label,
  help,
  htmlFor,
  children,
}: {
  label: string;
  help?: string;
  htmlFor?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label
        htmlFor={htmlFor}
        className="mb-1 block text-sm font-medium text-neutral-800"
      >
        {label}
        {help && (
          <span className="ml-2 text-xs font-normal text-neutral-500">
            {help}
          </span>
        )}
      </label>
      {children}
    </div>
  );
}

function toNonNegInt(e: ChangeEvent<HTMLInputElement>): number {
  const n = parseInt(e.target.value, 10);
  if (Number.isNaN(n) || n < 0) return 0;
  return n;
}

const inputCls =
  "w-full rounded-md border border-neutral-300 bg-white px-3 py-1.5 text-sm shadow-sm focus:border-neutral-500 focus:outline-none";
const textareaCls = `${inputCls} resize-y`;
const numberCls =
  "w-16 rounded-md border border-neutral-300 bg-white px-2 py-1 text-sm shadow-sm focus:border-neutral-500 focus:outline-none disabled:bg-neutral-100";
