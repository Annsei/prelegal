import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LoginPage from "./page";

let assignSpy: ReturnType<typeof vi.fn>;
let replaceSpy: ReturnType<typeof vi.fn>;

// Node 25 ships its own (empty, method-less) `globalThis.localStorage` that
// shadows happy-dom's. Inject a working in-memory implementation so
// `window.localStorage.setItem(...)` etc. work in tests.
function makeStorage(): Storage {
  const store = new Map<string, string>();
  return {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (k) => (store.has(k) ? store.get(k)! : null),
    key: (i) => Array.from(store.keys())[i] ?? null,
    removeItem: (k) => void store.delete(k),
    setItem: (k, v) => void store.set(k, String(v)),
  };
}

beforeEach(() => {
  assignSpy = vi.fn();
  replaceSpy = vi.fn();
  // Override individual location methods rather than the whole object —
  // happy-dom ties window.location to its BrowserWindow internals, so
  // replacing it wholesale breaks other window globals.
  vi.spyOn(window.location, "assign").mockImplementation(assignSpy);
  vi.spyOn(window.location, "replace").mockImplementation(replaceSpy);
  const storage = makeStorage();
  vi.stubGlobal("localStorage", storage);
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: storage,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// The default locale is "zh"; switch to English up front to keep the
// assertions readable for English speakers and stable against zh copy
// changes. Returns once the English label is visible.
async function switchToEnglish(): Promise<void> {
  await userEvent.click(screen.getByRole("button", { name: /english/i }));
}

describe("LoginPage", () => {
  it("calls /api/auth/login with password and stores the session", async () => {
    const session = {
      user: {
        id: 1,
        email: "alice@example.com",
        name: "",
        created_at: "2026-04-25T00:00:00",
      },
      token: "tok-abc",
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(session), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<LoginPage />);
    await switchToEnglish();
    await userEvent.type(
      screen.getByLabelText(/email/i),
      "alice@example.com",
    );
    await userEvent.type(
      screen.getByLabelText(/password/i),
      "secretpw1",
    );
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/auth/login");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      email: "alice@example.com",
      password: "secretpw1",
    });

    await waitFor(() => expect(assignSpy).toHaveBeenCalledWith("/"));
    // Session blob includes both user and token under the new key.
    const stored = window.localStorage.getItem("prelegal:session");
    expect(stored).toContain("alice@example.com");
    expect(stored).toContain("tok-abc");
  });

  it("shows an error message when the request fails", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "email already registered" }), {
        status: 409,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<LoginPage />);
    await switchToEnglish();
    // Switch to register so we hit a path that can 409.
    await userEvent.click(
      screen.getByRole("button", { name: /don't have an account/i }),
    );
    await userEvent.type(
      screen.getByLabelText(/email/i),
      "bob@example.com",
    );
    await userEvent.type(
      screen.getByLabelText(/password/i),
      "secretpw1",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /create account/i }),
    );

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        /email already registered/i,
      ),
    );
    expect(assignSpy).not.toHaveBeenCalled();
    expect(window.localStorage.getItem("prelegal:session")).toBeNull();
  });
});
