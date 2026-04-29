"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Disclaimer } from "@/components/Disclaimer";
import { DocumentSidebar } from "@/components/DocumentSidebar";
import { GenericDocPreview } from "@/components/GenericDocPreview";
import { LanguageToggle } from "@/components/LanguageToggle";
import { MNDAChat } from "@/components/MNDAChat";
import { MNDAForm } from "@/components/MNDAForm";
import { MNDAPreview } from "@/components/MNDAPreview";
import { SaveStatus, type SaveState } from "@/components/SaveStatus";
import {
  ApiError,
  type ChatTurn,
  documentsApi,
  type DocumentRecord,
  type DocumentSummary,
  type User,
} from "@/lib/api";
import type { Locale } from "@/lib/i18n";
import { useDictionary } from "@/lib/i18n";
import { INITIAL_STATE, type MndaState } from "@/lib/mndaState";
import { clearSession, readSession, readToken } from "@/lib/session";

type EditMode = "chat" | "form";

const MNDA_DOC_ID = "mutual-nda";
const AUTOSAVE_DEBOUNCE_MS = 800;
// Remembers which draft the user was last editing so a page refresh
// (within the same server lifetime) drops them back where they were.
// Stored separately from the session — clearing one shouldn't lose the
// other.
const ACTIVE_DOC_KEY = "prelegal:activeDocId";

// Wrapped shape we persist into a document's `state_json` column. The
// chat history goes in `chat`; the rest is either MndaState (for
// mutual-nda) or a free-form key/value map (for any other doc). Older
// rows from before this format existed will be missing `chat` — we
// treat that as "fresh chat".
type SavedDocState = {
  chat?: ChatTurn[];
  mnda?: Partial<MndaState>;
  fields?: Record<string, string>;
};

function isChatTurnArray(value: unknown): value is ChatTurn[] {
  return (
    Array.isArray(value) &&
    value.every(
      (turn) =>
        turn !== null &&
        typeof turn === "object" &&
        (turn as ChatTurn).role !== undefined &&
        typeof (turn as ChatTurn).content === "string",
    )
  );
}

function readActiveDocId(): number | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(ACTIVE_DOC_KEY);
  if (!raw) return null;
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function writeActiveDocId(id: number | null): void {
  if (typeof window === "undefined") return;
  if (id == null) window.localStorage.removeItem(ACTIVE_DOC_KEY);
  else window.localStorage.setItem(ACTIVE_DOC_KEY, String(id));
}

// Cover-page-style role keys the LLM emits for non-MNDA docs (see the
// system prompt in backend/app/llm.py). We match the title-derivation
// keys against these.
const ROLE_KEYS = [
  "Customer",
  "Provider",
  "Recipient",
  "Discloser",
  "Buyer",
  "Seller",
] as const;

// Compose the document title from chat-collected fields. For MNDA we use
// the two party companies, falling back to a generic label; for other
// docs we look at common cover-page keys.
function deriveTitle(
  docId: string,
  docTitleFor: (id: string) => string,
  state: MndaState,
  fields: Record<string, string>,
): string {
  if (docId === MNDA_DOC_ID) {
    const a = state.party1.company.trim();
    const b = state.party2.company.trim();
    if (a && b) return `${a} × ${b} MNDA`;
    if (a || b) return `${a || b} MNDA`;
    return "Mutual NDA draft";
  }
  const hits = ROLE_KEYS.map((k) => fields[k]?.trim()).filter(
    (v): v is string => Boolean(v),
  );
  const titleByCatalog = docTitleFor(docId);
  return hits.length > 0
    ? `${hits.join(" × ")} — ${titleByCatalog}`
    : titleByCatalog;
}

export default function Home() {
  const [locale, setLocale] = useState<Locale>("zh");
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);

  const [mode, setMode] = useState<EditMode>("chat");
  const [docId, setDocId] = useState<string>(MNDA_DOC_ID);
  const [state, setState] = useState<MndaState>(INITIAL_STATE);
  const [genericFields, setGenericFields] = useState<Record<string, string>>(
    {},
  );
  const [chatHistory, setChatHistory] = useState<ChatTurn[]>([]);

  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  // The DB row id of whichever draft is currently being edited. null means
  // the user has unsaved local edits that haven't been POSTed yet.
  const [activeDocId, setActiveDocId] = useState<number | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("idle");

  // Bumped on each user-initiated reset (new draft, switching docs) so
  // the auto-save effect ignores the synthetic state change that comes
  // with the load. Without this, switching from doc A to doc B would
  // immediately overwrite A's state with B's loaded state.
  const lastLoadedKey = useRef<string>("");
  const autosaveHandle = useRef<ReturnType<typeof setTimeout> | null>(null);
  // While a "create new draft" POST is in flight we hold the token here
  // so a second debounce that fires before setActiveDocId propagates
  // doesn't race a duplicate row. Cleared once the POST resolves.
  const creating = useRef<boolean>(false);

  const t = useDictionary(locale);
  const lookupDocTitle = useCallback(
    (id: string) => t.catalogTitles[id] ?? id,
    [t],
  );

  useEffect(() => {
    const session = readSession();
    if (!session) {
      window.location.replace("/login");
      return;
    }
    setUser(session.user);
    setToken(session.token);
  }, []);

  const refreshList = useCallback(async () => {
    const tk = readToken();
    if (!tk) return;
    try {
      const list = await documentsApi.list(tk);
      setDocuments(list);
    } catch (err) {
      // 401 means our token expired (likely a server restart) — bounce.
      if (err instanceof ApiError && err.status === 401) {
        clearSession();
        window.location.replace("/login");
      }
    }
  }, []);

  useEffect(() => {
    if (token) void refreshList();
  }, [token, refreshList]);

  // initialRestoreDone is paired with the restore-effect lower in the
  // file so that we only attempt to rehydrate the last draft once per
  // mount; defining the ref here keeps it adjacent to its sibling state.
  const initialRestoreDone = useRef(false);

  // Auto-save: whenever the editable state changes, schedule a debounced
  // POST/PUT. Skipped on initial mount and immediately after loading
  // another draft (lastLoadedKey gating).
  useEffect(() => {
    if (!token) return;
    const key = `${docId}|${activeDocId ?? "new"}`;
    if (lastLoadedKey.current !== key) {
      // We just switched drafts; the state change is the load itself.
      lastLoadedKey.current = key;
      return;
    }

    if (autosaveHandle.current) clearTimeout(autosaveHandle.current);
    autosaveHandle.current = setTimeout(async () => {
      // Only one in-flight create at a time — if a second debounce ticked
      // while the first POST was still pending, drop it; the next state
      // change will reschedule with activeDocId already populated and the
      // PUT branch will pick it up.
      if (activeDocId == null && creating.current) return;

      const title = deriveTitle(docId, lookupDocTitle, state, genericFields);
      // Wrap chat history alongside the document data so refresh and
      // re-login can restore the conversation, not just the form fields.
      const wrappedState: SavedDocState =
        docId === MNDA_DOC_ID
          ? { chat: chatHistory, mnda: state }
          : { chat: chatHistory, fields: genericFields };
      const body = {
        title,
        state: wrappedState as unknown as Record<string, unknown>,
      };
      setSaveState("saving");
      try {
        if (activeDocId == null) {
          creating.current = true;
          const created = await documentsApi.create(token, {
            doc_id: docId,
            title: body.title,
            state: body.state,
          });
          setActiveDocId(created.id);
          writeActiveDocId(created.id);
          lastLoadedKey.current = `${docId}|${created.id}`;
        } else {
          await documentsApi.update(token, activeDocId, body);
        }
        setSaveState("saved");
        await refreshList();
      } catch (err) {
        setSaveState("failed");
        if (err instanceof ApiError && err.status === 401) {
          clearSession();
          window.location.replace("/login");
        }
      } finally {
        creating.current = false;
      }
    }, AUTOSAVE_DEBOUNCE_MS);

    return () => {
      if (autosaveHandle.current) clearTimeout(autosaveHandle.current);
    };
  }, [
    token,
    docId,
    state,
    genericFields,
    chatHistory,
    activeDocId,
    refreshList,
    lookupDocTitle,
  ]);

  // The chat may decide to switch the user to a different catalog doc
  // mid-conversation. When that happens we MUST clear `activeDocId` —
  // otherwise the next debounced auto-save would PUT the new doc's
  // content into the previous doc's row.
  const onChatDocChange = useCallback(
    (newDocId: string) => {
      if (newDocId !== docId) {
        setActiveDocId(null);
        writeActiveDocId(null);
        setSaveState("idle");
        lastLoadedKey.current = `${newDocId}|new`;
      }
      setDocId(newDocId);
    },
    [docId],
  );

  const startNewDraft = useCallback(() => {
    setDocId(MNDA_DOC_ID);
    setState(INITIAL_STATE);
    setGenericFields({});
    setChatHistory([]);
    setActiveDocId(null);
    writeActiveDocId(null);
    setSaveState("idle");
    // Force the autosave gate to skip the next state-change tick (the
    // resets above) so we don't immediately POST an empty draft.
    lastLoadedKey.current = `${MNDA_DOC_ID}|new`;
  }, []);

  const loadDraftFromRecord = useCallback((rec: DocumentRecord) => {
    // Saved state is wrapped: { chat?, mnda?, fields? }. Decode each
    // piece defensively — bad/missing data falls back to a fresh draft.
    const saved = (rec.state ?? {}) as SavedDocState;
    setDocId(rec.doc_id);
    if (rec.doc_id === MNDA_DOC_ID) {
      setState({ ...INITIAL_STATE, ...(saved.mnda ?? {}) });
      setGenericFields({});
    } else {
      setState(INITIAL_STATE);
      setGenericFields(
        saved.fields && typeof saved.fields === "object" ? saved.fields : {},
      );
    }
    setChatHistory(isChatTurnArray(saved.chat) ? saved.chat : []);
    setActiveDocId(rec.id);
    writeActiveDocId(rec.id);
    setSaveState("saved");
    lastLoadedKey.current = `${rec.doc_id}|${rec.id}`;
  }, []);

  // After mount, if the user had a draft open before refreshing or
  // signing back in, fetch it and restore the editor. Runs once per
  // mount (gated by initialRestoreDone) and silently no-ops if the
  // remembered id has been deleted on the server.
  useEffect(() => {
    if (!token || initialRestoreDone.current) return;
    initialRestoreDone.current = true;
    const lastId = readActiveDocId();
    if (lastId == null) return;
    void documentsApi
      .get(token, lastId)
      .then(loadDraftFromRecord)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) {
          writeActiveDocId(null);
          return;
        }
        if (err instanceof ApiError && err.status === 401) {
          clearSession();
          window.location.replace("/login");
        }
      });
  }, [token, loadDraftFromRecord]);

  const onSelectDoc = useCallback(
    async (id: number) => {
      const tk = readToken();
      if (!tk) return;
      try {
        const rec = await documentsApi.get(tk, id);
        loadDraftFromRecord(rec);
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          clearSession();
          window.location.replace("/login");
        }
      }
    },
    [loadDraftFromRecord],
  );

  const onSignOut = useCallback(async () => {
    const tk = readToken();
    if (tk) {
      try {
        const { auth } = await import("@/lib/api");
        await auth.logout(tk);
      } catch {
        // Server may already have invalidated the token; clearing
        // local state is enough either way.
      }
    }
    clearSession();
    // Clear the last-active pointer too, otherwise the next user to log
    // into the same browser would inherit a stale id and 404 on restore.
    writeActiveDocId(null);
    window.location.assign("/login");
  }, []);

  const isMnda = docId === MNDA_DOC_ID;
  const docTitle = useMemo(() => lookupDocTitle(docId), [docId]);

  if (!user || !token) {
    // Don't render the platform until we've confirmed a session exists.
    // The effect above will redirect to /login if not.
    return null;
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="no-print border-b border-neutral-200 bg-white">
        <div className="mx-auto flex max-w-[1400px] items-center justify-between px-6 py-3">
          <div className="flex items-baseline gap-3">
            <h1 className="text-base font-semibold text-neutral-900">
              {t.appTitle}
            </h1>
            <span className="text-xs" style={{ color: "#888888" }}>
              {t.drafting}:{" "}
              <span style={{ color: "#753991" }}>{docTitle}</span>
            </span>
            <SaveStatus locale={locale} state={saveState} />
          </div>
          <div className="flex items-center gap-2">
            <span
              className="hidden text-xs sm:inline"
              style={{ color: "#888888" }}
              title={user.email}
            >
              {user.email}
            </span>
            <button
              type="button"
              onClick={onSignOut}
              className="rounded-md border border-neutral-300 bg-white px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
            >
              {t.signOut}
            </button>
            <LanguageToggle
              locale={locale}
              onToggle={() => setLocale(locale === "zh" ? "en" : "zh")}
            />
            <button
              type="button"
              onClick={() => window.print()}
              className="rounded-md bg-neutral-900 px-4 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-neutral-700"
              title={t.printHint}
            >
              {t.download}
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto grid w-full max-w-[1400px] flex-1 grid-cols-1 gap-5 px-6 py-5 lg:grid-cols-[220px_minmax(320px,440px)_1fr]">
        <DocumentSidebar
          locale={locale}
          documents={documents}
          activeId={activeDocId}
          catalogTitleFor={lookupDocTitle}
          onSelect={onSelectDoc}
          onCreate={startNewDraft}
        />

        <div className="no-print">
          <div role="tablist" className="mb-3 flex gap-2">
            <ModeTab
              active={mode === "chat"}
              onClick={() => setMode("chat")}
              label={t.chat.tab}
            />
            {isMnda && (
              <ModeTab
                active={mode === "form"}
                onClick={() => setMode("form")}
                label={t.chat.formTab}
              />
            )}
          </div>
          {mode === "chat" || !isMnda ? (
            <MNDAChat
              // Tear down + remount when the user switches drafts so any
              // ephemeral chat state (the "done" banner, in-flight errors)
              // resets without us having to plumb every flag through props.
              key={activeDocId ?? "new"}
              locale={locale}
              state={state}
              onStateChange={setState}
              onDocChange={onChatDocChange}
              onFieldUpdates={(updates) =>
                setGenericFields((prev) => ({ ...prev, ...updates }))
              }
              history={chatHistory}
              onHistoryChange={setChatHistory}
            />
          ) : (
            <div className="rounded-lg border border-neutral-200 bg-white p-5 shadow-sm">
              <MNDAForm locale={locale} value={state} onChange={setState} />
            </div>
          )}
          <p className="mt-3 text-xs text-neutral-500">{t.printHint}</p>
        </div>

        <div>
          <Disclaimer locale={locale} variant="banner" />
          {isMnda ? (
            <MNDAPreview value={state} />
          ) : (
            <GenericDocPreview
              docId={docId}
              fields={genericFields}
              locale={locale}
            />
          )}
        </div>
      </main>

      <Disclaimer locale={locale} variant="footer" />
    </div>
  );
}

function ModeTab({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className="rounded-md px-3 py-1.5 text-sm font-medium"
      style={{
        background: active ? "#209dd7" : "white",
        color: active ? "white" : "#032147",
        border: `1px solid ${active ? "#209dd7" : "#d4d4d4"}`,
      }}
    >
      {label}
    </button>
  );
}
