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

type FetchOptions = RequestInit & {
  // Pass an explicit bearer token on protected calls. Read from the session
  // helper at the callsite so the api module stays storage-agnostic.
  token?: string | null;
};

export async function apiFetch<T>(
  path: string,
  init: FetchOptions = {},
): Promise<T> {
  const { token, headers: extraHeaders, ...rest } = init;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(extraHeaders as Record<string, string> | undefined),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...rest, headers });
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
  // 204 No Content: nothing to parse.
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export type User = {
  id: number;
  email: string;
  name: string;
  created_at: string;
};

export type SessionResponse = { user: User; token: string };

export const auth = {
  login: (email: string, password: string) =>
    apiFetch<SessionResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  register: (email: string, password: string, name: string) =>
    apiFetch<SessionResponse>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, name }),
    }),
  logout: (token: string) =>
    apiFetch<void>("/api/auth/logout", { method: "POST", token }),
  me: (token: string) => apiFetch<User>("/api/auth/me", { token }),
};

export type ChatTurn = { role: "user" | "assistant"; content: string };

export type ChatResponse = {
  assistant_message: string;
  selected_doc_id: string;
  mnda_updates: Record<string, unknown>;
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

export type DocumentSummary = {
  id: number;
  doc_id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type DocumentRecord = DocumentSummary & {
  state: Record<string, unknown>;
};

export const documentsApi = {
  list: (token: string) =>
    apiFetch<DocumentSummary[]>("/api/documents", { token }),
  create: (
    token: string,
    body: { doc_id: string; title?: string; state?: Record<string, unknown> },
  ) =>
    apiFetch<DocumentRecord>("/api/documents", {
      method: "POST",
      token,
      body: JSON.stringify(body),
    }),
  get: (token: string, id: number) =>
    apiFetch<DocumentRecord>(`/api/documents/${id}`, { token }),
  update: (
    token: string,
    id: number,
    body: { title?: string; state?: Record<string, unknown> },
  ) =>
    apiFetch<DocumentRecord>(`/api/documents/${id}`, {
      method: "PUT",
      token,
      body: JSON.stringify(body),
    }),
  delete: (token: string, id: number) =>
    apiFetch<void>(`/api/documents/${id}`, { method: "DELETE", token }),
};
