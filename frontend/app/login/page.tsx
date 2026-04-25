"use client";

import { useState } from "react";
import { ApiError, auth } from "@/lib/api";
import { writeUser } from "@/lib/session";

type Mode = "login" | "register";

export default function LoginPage() {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const user =
        mode === "login"
          ? await auth.login(email)
          : await auth.register(email, name);
      writeUser(user);
      // Hard navigation: this is a static export, so we want the browser to
      // load index.html fresh and pick up the stored session.
      window.location.assign("/");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-neutral-50 px-4">
      <div className="w-full max-w-sm rounded-lg border border-neutral-200 bg-white p-6 shadow-sm">
        <h1
          className="mb-1 text-xl font-semibold"
          style={{ color: "#032147" }}
        >
          Prelegal
        </h1>
        <p className="mb-6 text-sm" style={{ color: "#888888" }}>
          {mode === "login"
            ? "Sign in to continue."
            : "Create an account to continue."}
        </p>

        <form className="space-y-4" onSubmit={onSubmit}>
          <div>
            <label
              htmlFor="email"
              className="mb-1 block text-sm font-medium text-neutral-800"
            >
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-md border border-neutral-300 bg-white px-3 py-1.5 text-sm shadow-sm focus:outline-none"
              style={{ borderColor: "#d4d4d4" }}
            />
          </div>

          {mode === "register" && (
            <div>
              <label
                htmlFor="name"
                className="mb-1 block text-sm font-medium text-neutral-800"
              >
                Name <span className="text-xs text-neutral-500">(optional)</span>
              </label>
              <input
                id="name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full rounded-md border border-neutral-300 bg-white px-3 py-1.5 text-sm shadow-sm focus:outline-none"
              />
            </div>
          )}

          {error && (
            <p role="alert" className="text-sm text-red-600">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-md px-4 py-2 text-sm font-medium text-white shadow-sm disabled:opacity-60"
            style={{ backgroundColor: "#753991" }}
          >
            {submitting
              ? "…"
              : mode === "login"
                ? "Sign in"
                : "Create account"}
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
            ? "Don't have an account? Register"
            : "Already have an account? Sign in"}
        </button>
      </div>
    </main>
  );
}
