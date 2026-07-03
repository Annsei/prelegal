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

// localStorage access can throw (Safari private mode, storage disabled via
// browser policy, non-browser test environments). Treat any failure as
// "no storage": reads return null, writes are dropped — the user just
// gets a session that doesn't survive a reload instead of a crash.
function safeStorageGet(key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeStorageSet(key: string, value: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Storage unavailable — session won't survive a reload; not fatal.
  }
}

function safeStorageRemove(key: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(key);
  } catch {
    // Nothing stored anyway if storage is unavailable.
  }
}

export function readSession(): Session | null {
  const raw = safeStorageGet(KEY);
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
  safeStorageSet(KEY, JSON.stringify(session));
}

export function clearSession(): void {
  safeStorageRemove(KEY);
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
