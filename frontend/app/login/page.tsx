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
    <main className="min-h-screen">
      <div className="grid min-h-screen items-stretch lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        {/* Marketing column — hidden on mobile so the form takes the whole
            screen and remains the focus. */}
        <section
          className="ledger relative hidden flex-col justify-between overflow-hidden p-12 lg:flex"
          style={{ background: "#032147", color: "#f3ede0" }}
        >
          {/* Oversized watermark glyph — 契, the character for "deed". */}
          <span
            aria-hidden
            className="display pointer-events-none absolute -bottom-24 -right-10 select-none leading-none"
            style={{ fontSize: "26rem", color: "rgba(236, 173, 10, 0.06)" }}
          >
            契
          </span>

          <div className="reveal reveal-1">
            <p
              className="display text-base tracking-[0.3em]"
              style={{ color: "#ecad0a" }}
            >
              Prelegal
            </p>
          </div>

          <div className="relative">
            <div className="seal reveal reveal-2 mb-10">
              <span
                aria-hidden
                className="display text-5xl"
                style={{ color: "#ecad0a" }}
              >
                契
              </span>
            </div>
            <h1 className="display reveal reveal-2 max-w-md text-4xl leading-snug">
              {t.auth.welcome}
            </h1>
            <p
              className="reveal reveal-3 mt-5 max-w-md text-sm leading-relaxed"
              style={{ color: "#b9c8da" }}
            >
              {t.auth.pitch}
            </p>
            <div
              className="reveal reveal-3 mt-8 h-px w-24"
              style={{ background: "rgba(236, 173, 10, 0.6)" }}
            />
          </div>

          <p
            className="reveal reveal-4 max-w-md text-xs leading-relaxed"
            style={{ color: "#8aa5c0" }}
          >
            {t.disclaimer}
          </p>
        </section>

        <section className="flex flex-col items-center justify-center px-6 py-10">
          <div className="flex w-full max-w-sm flex-col">
            <div className="reveal reveal-1 mb-6 flex items-center justify-between">
              <p
                className="display text-lg tracking-wide lg:invisible"
                style={{ color: "#032147" }}
              >
                <span aria-hidden style={{ color: "#ecad0a" }}>
                  契
                </span>{" "}
                Prelegal
              </p>
              <LanguageToggle
                locale={locale}
                onToggle={() => setLocale(locale === "zh" ? "en" : "zh")}
              />
            </div>
            <div className="card reveal reveal-2 p-8">
              <h2
                className="display text-2xl"
                style={{ color: "#032147" }}
              >
                {mode === "login" ? t.auth.signInTitle : t.auth.registerTitle}
              </h2>
              <div
                className="mt-2 h-px w-10"
                style={{ background: "#ecad0a" }}
              />

              <form className="mt-6 space-y-4" onSubmit={onSubmit}>
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
                  className="btn btn-primary w-full"
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
                className="mt-5 w-full text-center text-sm hover:underline"
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

            <div className="reveal reveal-3 mt-6 lg:hidden">
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
        className="mb-1 block text-sm font-medium"
        style={{ color: "#40536d" }}
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
        className="input-field"
      />
      {helper && (
        <p className="mt-1 text-xs" style={{ color: "#888888" }}>
          {helper}
        </p>
      )}
    </div>
  );
}
