// Tiny client-side session — purely a placeholder for v1. There is no token
// or signed cookie; the backend has no auth gate either. The point is just
// to remember which user clicked through the fake login screen so we can
// show their email in the header.

import type { User } from "@/lib/api";

const KEY = "prelegal:user";

export function readUser(): User | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as User;
  } catch {
    return null;
  }
}

export function writeUser(user: User): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(KEY, JSON.stringify(user));
}

export function clearUser(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(KEY);
}
