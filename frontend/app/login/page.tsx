"use client";

import { useState } from "react";
import { Disclaimer } from "@/components/Disclaimer";
import { LanguageToggle } from "@/components/LanguageToggle";
import { ApiError, auth } from "@/lib/api";
import type { Locale } from "@/lib/i18n";
import { useDictionary } from "@/lib/i18n";
import { writeSession } from "@/lib/session";

type Mode = "login" | "register";

export default function LoginPage() {
  const [locale, setLocale] = useState<Locale>("zh");
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const t = useDictionary(locale);

  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const session =
        mode === "login"
          ? await auth.login(email, password)
          : await auth.register(email, password, name);
      writeSession(session);
      // Hard navigation: this is a static export, so we want the browser to
      // load index.html fresh and pick up the stored session.
      window.location.assign("/");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError(t.auth.genericError);
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="min-h-screen bg-neutral-50">
      <div className="mx-auto grid min-h-screen max-w-6xl items-stretch px-4 lg:grid-cols-2">
        {/* Marketing column — hidden on mobile so the form takes the whole
            screen and remains the focus. */}
        <section
          className="hidden flex-col justify-between p-12 lg:flex"
          style={{ background: "#032147", color: "white" }}
        >
          <div>
            <p
              className="text-xs uppercase tracking-widest"
              style={{ color: "#ecad0a" }}
            >
              Prelegal
            </p>
            <h1 className="mt-3 text-3xl font-semibold leading-tight">
              {t.auth.welcome}
            </h1>
            <p className="mt-4 text-sm leading-relaxed text-neutral-200">
              {t.auth.pitch}
            </p>
          </div>
          <p
            className="text-xs leading-relaxed"
            style={{ color: "#aac9e1" }}
          >
            {t.disclaimer}
          </p>
        </section>

        <section className="flex flex-col items-center justify-center px-6 py-10">
          <div className="flex w-full max-w-sm flex-col">
            <div className="mb-6 flex justify-end">
              <LanguageToggle
                locale={locale}
                onToggle={() => setLocale(locale === "zh" ? "en" : "zh")}
              />
            </div>
            <div className="rounded-xl border border-neutral-200 bg-white p-7 shadow-sm">
              <h2
                className="text-xl font-semibold"
                style={{ color: "#032147" }}
              >
                {mode === "login" ? t.auth.signInTitle : t.auth.registerTitle}
              </h2>

              <form className="mt-5 space-y-4" onSubmit={onSubmit}>
                <Field
                  id="email"
                  label={t.auth.email}
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={setEmail}
                  required
                />
                {mode === "register" && (
                  <Field
                    id="name"
                    label={`${t.auth.name} ${t.auth.nameOptional}`}
                    type="text"
                    autoComplete="name"
                    value={name}
                    onChange={setName}
                  />
                )}
                <Field
                  id="password"
                  label={t.auth.password}
                  helper={
                    mode === "register" ? t.auth.passwordHelp : undefined
                  }
                  type="password"
                  autoComplete={
                    mode === "login" ? "current-password" : "new-password"
                  }
                  value={password}
                  onChange={setPassword}
                  minLength={mode === "register" ? 8 : 1}
                  required
                />

                {error && (
                  <p role="alert" className="text-sm text-red-600">
                    {error}
                  </p>
                )}

                <button
                  type="submit"
                  disabled={submitting}
                  className="w-full rounded-md px-4 py-2 text-sm font-medium text-white shadow-sm transition-opacity disabled:opacity-60"
                  style={{ backgroundColor: "#753991" }}
                >
                  {submitting
                    ? t.auth.submitting
                    : mode === "login"
                      ? t.auth.signInCta
                      : t.auth.registerCta}
                </button>
              </form>

              <button
                type="button"
                className="mt-4 w-full text-center text-sm hover:underline"
                style={{ color: "#209dd7" }}
                onClick={() => {
                  setError(null);
                  setMode(mode === "login" ? "register" : "login");
                }}
              >
                {mode === "login"
                  ? t.auth.switchToRegister
                  : t.auth.switchToLogin}
              </button>
            </div>

            <div className="mt-6 lg:hidden">
              <Disclaimer locale={locale} variant="compact" />
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

function Field({
  id,
  label,
  helper,
  type,
  value,
  onChange,
  required,
  minLength,
  autoComplete,
}: {
  id: string;
  label: string;
  helper?: string;
  type: "email" | "password" | "text";
  value: string;
  onChange: (v: string) => void;
  required?: boolean;
  minLength?: number;
  autoComplete?: string;
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="mb-1 block text-sm font-medium text-neutral-800"
      >
        {label}
      </label>
      <input
        id={id}
        type={type}
        required={required}
        minLength={minLength}
        autoComplete={autoComplete}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-[#209dd7] focus:outline-none focus:ring-1 focus:ring-[#209dd7]"
      />
      {helper && (
        <p className="mt-1 text-xs" style={{ color: "#888888" }}>
          {helper}
        </p>
      )}
    </div>
  );
}
