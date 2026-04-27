// Resolves to "" in production (Docker, same-origin) and a configurable
// override (e.g. "http://localhost:8000") for local frontend-only dev where
// `next dev` runs on a different port than FastAPI.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

export class ApiError extends Error {
  status: number;
  detail?: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = await res.json();
    } catch {
      detail = await res.text();
    }
    const message =
      typeof detail === "object" &&
      detail !== null &&
      "detail" in detail &&
      typeof (detail as { detail: unknown }).detail === "string"
        ? (detail as { detail: string }).detail
        : `Request failed with status ${res.status}`;
    throw new ApiError(res.status, message, detail);
  }
  return (await res.json()) as T;
}

export type User = {
  id: number;
  email: string;
  name: string;
  created_at: string;
};

export const auth = {
  login: (email: string) =>
    apiFetch<User>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  register: (email: string, name: string) =>
    apiFetch<User>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, name }),
    }),
};

export type ChatTurn = { role: "user" | "assistant"; content: string };

export type ChatResponse = {
  assistant_message: string;
  // Catalog id of the document the user is drafting; "" until intent is clear.
  selected_doc_id: string;
  // Partial of the frontend MndaState — only MNDA fields the AI just learned.
  mnda_updates: Record<string, unknown>;
  // Free-form key/value updates for non-MNDA documents (Cover-Page-level data).
  field_updates: Record<string, string>;
  done: boolean;
};

export const chatApi = {
  send: (messages: ChatTurn[], mndaState: Record<string, unknown>) =>
    apiFetch<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ messages, mnda_state: mndaState }),
    }),
};

export type TemplateResponse = {
  doc_id: string;
  title: string;
  standard_terms: string;
  cover_page: string | null;
};

export const templatesApi = {
  get: (docId: string) =>
    apiFetch<TemplateResponse>(`/api/templates/${encodeURIComponent(docId)}`),
};
