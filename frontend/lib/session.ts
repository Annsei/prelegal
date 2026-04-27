// Persisted session — token + user record.
//
// PL-7 introduced real auth: register/login return a bearer token; the
// frontend stores it here and sends it on protected calls. The DB on the
// backend resets on each restart, so a stored token may resolve to 401
// after a server bounce — `apiFetch` handles that by calling `clearUser`
// and the page-level guard then redirects to /login.

import type { User } from "@/lib/api";

const KEY = "prelegal:session";

export type Session = { user: User; token: string };

export function readSession(): Session | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<Session>;
    if (!parsed || !parsed.user || typeof parsed.token !== "string") return null;
    return parsed as Session;
  } catch {
    return null;
  }
}

export function writeSession(session: Session): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(KEY, JSON.stringify(session));
}

export function clearSession(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(KEY);
}

// Convenience accessors so callers don't have to read the full session.
export function readUser(): User | null {
  return readSession()?.user ?? null;
}

export function readToken(): string | null {
  return readSession()?.token ?? null;
}

export function clearUser(): void {
  clearSession();
}
