"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Disclaimer } from "@/components/Disclaimer";
import { DocForm } from "@/components/DocForm";
import { DocumentSidebar } from "@/components/DocumentSidebar";
import { GenericDocPreview } from "@/components/GenericDocPreview";
import { LanguageToggle } from "@/components/LanguageToggle";
import { MNDAChat } from "@/components/MNDAChat";
import { SaveStatus, type SaveState } from "@/components/SaveStatus";
import {
  displayFieldValues,
  isCompleteForDownload,
  readDraftStateSnapshot,
  stableFieldValues,
  type DraftStateSnapshot,
} from "@/lib/draftState";
import { localized } from "@/lib/docManifest";
import { useDocTemplate } from "@/lib/useDocTemplate";
import {
  ApiError,
  type ChatTurn,
  documentsApi,
  type DocumentRecord,
  type DocumentSummary,
  type FieldPatchOperation,
  type User,
} from "@/lib/api";
import type { Locale } from "@/lib/i18n";
import { useDictionary } from "@/lib/i18n";
import { clearSession, readSession, readToken } from "@/lib/session";

type EditMode = "chat" | "form";

const MNDA_DOC_ID = "mutual-nda";
const KERNEL_MANAGED_DOC_IDS = new Set([
  "cloud-service-agreement",
  MNDA_DOC_ID,
]);
const AUTOSAVE_DEBOUNCE_MS = 800;
// Remembers which draft the user was last editing so a page refresh
// (within the same server lifetime) drops them back where they were.
// Stored separately from the session — clearing one shouldn't lose the
// other.
const ACTIVE_DOC_KEY = "prelegal:activeDocId";

// Wrapped shape we persist into a document's `state_json` column. The
// chat history goes in `chat`; fallback docs keep a free-form key/value
// map in `fields`. Kernel-managed docs persist field values through
// `draft_state`; older rows from before this format existed will be
// missing `chat`, which we treat as "fresh chat".
type SavedDocState = {
  chat?: ChatTurn[];
  fields?: Record<string, string>;
  draft_state?: unknown;
};

function unresolvedRequiredFieldsFromError(err: unknown): string[] {
  if (!(err instanceof ApiError) || err.status !== 409) return [];
  const detail = err.detail;
  if (!detail || typeof detail !== "object") return [];
  const outer = detail as { detail?: unknown; unresolved_required_fields?: unknown };
  const nested =
    outer.detail && typeof outer.detail === "object"
      ? (outer.detail as { unresolved_required_fields?: unknown })
      : null;
  const raw =
    nested?.unresolved_required_fields ?? outer.unresolved_required_fields;
  if (!Array.isArray(raw)) return [];
  return raw.filter((key): key is string => typeof key === "string");
}

function newPatchId(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

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
  try {
    const raw = window.localStorage.getItem(ACTIVE_DOC_KEY);
    if (!raw) return null;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : null;
  } catch {
    // Storage unavailable (private mode / policy) — no draft to restore.
    return null;
  }
}

function writeActiveDocId(id: number | null): void {
  if (typeof window === "undefined") return;
  try {
    if (id == null) window.localStorage.removeItem(ACTIVE_DOC_KEY);
    else window.localStorage.setItem(ACTIVE_DOC_KEY, String(id));
  } catch {
    // Storage unavailable — the last-open-draft pointer just won't persist.
  }
}

// Cover-page-style party keys the LLM emits for manifest and fallback docs
// (they match the manifest field keys / template span names, which are
// Chinese in the PRC template library). We match title-derivation keys
// against these.
const ROLE_KEYS = [
  "客户",
  "服务方",
  "甲方",
  "乙方",
  "委托方",
  "受托方",
  "许可方",
  "被许可方",
  "供应商",
  "合作方",
  "医疗机构",
  "技术服务方",
] as const;

// Compose the document title from chat-collected fields. For MNDA we use
// the two party companies, falling back to a generic label; for other
// docs we look at common cover-page keys.
function deriveTitle(
  docId: string,
  docTitleFor: (id: string) => string,
  fields: Record<string, string>,
): string {
  if (docId === MNDA_DOC_ID) {
    const a = fields["甲方公司名称"]?.trim() ?? "";
    const b = fields["乙方公司名称"]?.trim() ?? "";
    if (a && b) return `${a} × ${b} 保密协议`;
    if (a || b) return `${a || b} 保密协议`;
    return "保密协议草稿";
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
  const [genericFields, setGenericFields] = useState<Record<string, string>>(
    {},
  );
  const [draftState, setDraftState] = useState<DraftStateSnapshot | null>(null);
  const [chatHistory, setChatHistory] = useState<ChatTurn[]>([]);
  const [downloadBlockedKeys, setDownloadBlockedKeys] = useState<string[]>([]);

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
  // Draft generation counter. Bumped whenever the user switches to a
  // different draft (sidebar click, new draft). In-flight async work that
  // started under an older generation (a slow /api/chat reply, a stale
  // sidebar GET) must discard its result instead of applying it to the
  // draft that is now on screen — otherwise the 800ms auto-save would
  // persist draft A's reply into draft B's DB row.
  const draftEpoch = useRef(0);
  const getDraftEpoch = useCallback(() => draftEpoch.current, []);
  // Monotonic ticket for sidebar selections. Rapid clicks A→B can resolve
  // out of order (A's GET returns after B's); only the latest click may
  // load, otherwise stale data overwrites what the user selected last.
  const selectSeq = useRef(0);
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
  const kernelManagedDoc = KERNEL_MANAGED_DOC_IDS.has(docId);
  const docTitle = useMemo(
    () => lookupDocTitle(docId),
    [docId, lookupDocTitle],
  );
  const templateLoad = useDocTemplate(docId, true, t.templateUnavailable);
  const manifest =
    templateLoad.kind === "ready" ? (templateLoad.template.manifest ?? null) : null;
  const stableGenericFields = manifest
    ? stableFieldValues(manifest, draftState, genericFields)
    : genericFields;
  const displayGenericFields = manifest
    ? displayFieldValues(manifest, draftState, genericFields)
    : genericFields;
  const downloadBlockedLabels = manifest
    ? downloadBlockedKeys.map((key) => {
        const field = manifest.fields.find((item) => item.key === key);
        return field ? localized(field.label, locale) : key;
      })
    : downloadBlockedKeys;

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

      const title = deriveTitle(docId, lookupDocTitle, displayGenericFields);
      // Wrap chat history alongside the document data so refresh and
      // re-login can restore the conversation, not just the form fields.
      const wrappedState: SavedDocState =
        kernelManagedDoc
          ? { chat: chatHistory }
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
    genericFields,
    displayGenericFields,
    kernelManagedDoc,
    chatHistory,
    draftState,
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
        setGenericFields({});
        setDraftState(null);
        setDownloadBlockedKeys([]);
        lastLoadedKey.current = `${newDocId}|new`;
      }
      setDocId(newDocId);
    },
    [docId],
  );

  const startNewDraft = useCallback(() => {
    draftEpoch.current += 1;
    // Invalidate any in-flight sidebar selection so its response can't
    // overwrite the fresh draft we're about to show.
    selectSeq.current += 1;
    setDocId(MNDA_DOC_ID);
    setGenericFields({});
    setDraftState(null);
    setDownloadBlockedKeys([]);
    setChatHistory([]);
    setActiveDocId(null);
    writeActiveDocId(null);
    setSaveState("idle");
    // Force the autosave gate to skip the next state-change tick (the
    // resets above) so we don't immediately POST an empty draft.
    lastLoadedKey.current = `${MNDA_DOC_ID}|new`;
  }, []);

  const loadDraftFromRecord = useCallback((rec: DocumentRecord) => {
    draftEpoch.current += 1;
    // Saved state is wrapped: { chat?, fields?, draft_state? }. Decode each
    // piece defensively — bad/missing data falls back to a fresh draft.
    const saved = (rec.state ?? {}) as SavedDocState;
    setDocId(rec.doc_id);
    setGenericFields(
      saved.fields && typeof saved.fields === "object" ? saved.fields : {},
    );
    setDraftState(readDraftStateSnapshot(saved.draft_state));
    setDownloadBlockedKeys([]);
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
      const ticket = ++selectSeq.current;
      try {
        const rec = await documentsApi.get(tk, id);
        if (ticket !== selectSeq.current) return;
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

  const handleAuthError = useCallback((err: unknown) => {
    if (err instanceof ApiError && err.status === 401) {
      clearSession();
      window.location.replace("/login");
      return true;
    }
    return false;
  }, []);

  const ensureDocumentForPatch = useCallback(
    async (
      targetDocId: string,
      historyForState: ChatTurn[],
    ): Promise<{ id: number; revision: number }> => {
      const tk = readToken();
      if (!tk) throw new Error("Missing session token.");
      if (activeDocId != null && targetDocId === docId) {
        return { id: activeDocId, revision: draftState?.revision ?? 0 };
      }

      creating.current = true;
      try {
        const created = await documentsApi.create(tk, {
          doc_id: targetDocId,
          title: deriveTitle(
            targetDocId,
            lookupDocTitle,
            displayGenericFields,
          ),
          state: { chat: historyForState },
        });
        const saved = (created.state ?? {}) as SavedDocState;
        const createdSnapshot = readDraftStateSnapshot(saved.draft_state);
        if (targetDocId !== docId) {
          setDocId(targetDocId);
          setGenericFields({});
        }
        setDraftState(createdSnapshot);
        setDownloadBlockedKeys([]);
        setActiveDocId(created.id);
        writeActiveDocId(created.id);
        lastLoadedKey.current = `${targetDocId}|${created.id}`;
        setSaveState("saved");
        await refreshList();
        return { id: created.id, revision: createdSnapshot?.revision ?? 0 };
      } finally {
        creating.current = false;
      }
    },
    [
      activeDocId,
      displayGenericFields,
      docId,
      draftState,
      lookupDocTitle,
      refreshList,
    ],
  );

  const applyChatFieldUpdates = useCallback(
    async (
      updates: Record<string, string>,
      context: {
        docId: string;
        history: ChatTurn[];
        messageIndex: number;
      },
    ) => {
      if (!KERNEL_MANAGED_DOC_IDS.has(context.docId)) {
        setGenericFields((prev) => ({ ...prev, ...updates }));
        return;
      }
      const operations: FieldPatchOperation[] = Object.entries(updates)
        .filter(([, value]) => typeof value === "string" && value.trim() !== "")
        .map(([key, value]) => ({ op: "propose", key, value }));
      if (operations.length === 0) return;
      const tk = readToken();
      if (!tk) throw new Error("Missing session token.");
      setSaveState("saving");
      try {
        const { id, revision } = await ensureDocumentForPatch(
          context.docId,
          context.history,
        );
        const result = await documentsApi.fieldPatch(tk, id, {
          patch_id: newPatchId("llm"),
          base_revision: revision,
          source: "llm",
          message_index: context.messageIndex,
          operations,
        });
        setDraftState(result.snapshot);
        setDownloadBlockedKeys([]);
        setSaveState("saved");
        await refreshList();
      } catch (err) {
        setSaveState("failed");
        handleAuthError(err);
        throw err;
      }
    },
    [ensureDocumentForPatch, handleAuthError, refreshList],
  );

  const confirmField = useCallback(
    async (key: string, value: string) => {
      if (!kernelManagedDoc) return;
      const tk = readToken();
      if (!tk) return;
      setSaveState("saving");
      try {
        const { id, revision } = await ensureDocumentForPatch(docId, chatHistory);
        const result = await documentsApi.fieldPatch(tk, id, {
          patch_id: newPatchId("form-confirm"),
          base_revision: revision,
          source: "form",
          operations: [{ op: "confirm", key, value }],
        });
        setDraftState(result.snapshot);
        setDownloadBlockedKeys([]);
        setSaveState("saved");
        await refreshList();
      } catch (err) {
        setSaveState("failed");
        handleAuthError(err);
      }
    },
    [
      chatHistory,
      docId,
      ensureDocumentForPatch,
      handleAuthError,
      kernelManagedDoc,
      refreshList,
    ],
  );

  const rejectField = useCallback(
    async (key: string) => {
      if (!kernelManagedDoc || activeDocId == null) return;
      const tk = readToken();
      if (!tk) return;
      setSaveState("saving");
      try {
        const result = await documentsApi.fieldPatch(tk, activeDocId, {
          patch_id: newPatchId("form-reject"),
          base_revision: draftState?.revision ?? 0,
          source: "form",
          operations: [{ op: "reject", key }],
        });
        setDraftState(result.snapshot);
        setDownloadBlockedKeys([]);
        setSaveState("saved");
        await refreshList();
      } catch (err) {
        setSaveState("failed");
        handleAuthError(err);
      }
    },
    [
      activeDocId,
      draftState,
      handleAuthError,
      kernelManagedDoc,
      refreshList,
    ],
  );

  const manifestComplete =
    manifest !== null && isCompleteForDownload(manifest, draftState);
  // Manifest docs unlock download once every required cover-page field has
  // a confirmed value; docs without a manifest can't download at all — the
  // output would be a raw unpopulated template.
  const canDownload = manifestComplete;
  const downloadTitle = canDownload
    ? t.printHint
    : manifest
      ? t.downloadIncomplete
      : t.downloadUnavailable;

  const handleDownload = useCallback(async () => {
    if (!manifest || activeDocId == null) return;
    const tk = readToken();
    if (!tk) return;
    try {
      await documentsApi.downloadReadiness(tk, activeDocId);
      setDownloadBlockedKeys([]);
      window.print();
    } catch (err) {
      const blockedKeys = unresolvedRequiredFieldsFromError(err);
      if (blockedKeys.length > 0) {
        setDownloadBlockedKeys(blockedKeys);
        return;
      }
      setSaveState("failed");
      handleAuthError(err);
    }
  }, [activeDocId, handleAuthError, manifest]);

  if (!user || !token) {
    // Don't render the platform until we've confirmed a session exists.
    // The effect above will redirect to /login if not.
    return null;
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header
        className="no-print sticky top-0 z-40 border-b backdrop-blur"
        style={{
          borderColor: "var(--rule)",
          background: "rgba(245, 240, 228, 0.85)",
        }}
      >
        <div className="mx-auto flex max-w-[1400px] items-center justify-between px-6 py-3">
          <div className="flex items-baseline gap-3">
            <span
              aria-hidden
              className="display self-center text-lg leading-none"
              style={{ color: "var(--gold)" }}
            >
              契
            </span>
            <h1
              className="display text-lg tracking-wide"
              style={{ color: "var(--ink)" }}
            >
              {t.appTitle}
            </h1>
            <span
              className="hidden items-baseline gap-1 rounded-full border px-3 py-0.5 text-xs md:inline-flex"
              style={{ borderColor: "var(--rule)", color: "var(--ink-3)" }}
            >
              {t.drafting}:{" "}
              <span className="font-medium" style={{ color: "var(--purple)" }}>
                {docTitle}
              </span>
            </span>
            <SaveStatus locale={locale} state={saveState} />
          </div>
          <div className="flex items-center gap-2">
            <span
              className="hidden text-xs sm:inline"
              style={{ color: "var(--ink-3)" }}
              title={user.email}
            >
              {user.email}
            </span>
            <button
              type="button"
              onClick={onSignOut}
              className="btn btn-ghost"
            >
              {t.signOut}
            </button>
            <LanguageToggle
              locale={locale}
              onToggle={() => setLocale(locale === "zh" ? "en" : "zh")}
            />
            <button
              type="button"
              onClick={() => void handleDownload()}
              disabled={!canDownload}
              className="btn btn-ink"
              title={downloadTitle}
            >
              {t.download}
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto grid w-full max-w-[1400px] flex-1 grid-cols-1 gap-6 px-6 py-6 lg:grid-cols-[230px_minmax(320px,440px)_1fr]">
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
            {manifest !== null && (
              <ModeTab
                active={mode === "form"}
                onClick={() => setMode("form")}
                label={t.chat.formTab}
              />
            )}
          </div>
          {mode === "chat" || manifest === null ? (
            <MNDAChat
              // Tear down + remount when the user switches drafts so any
              // ephemeral chat state (the "done" banner, in-flight errors)
              // resets without us having to plumb every flag through props.
              key={activeDocId ?? "new"}
              locale={locale}
              fields={stableGenericFields}
              docId={docId}
              getDraftEpoch={getDraftEpoch}
              onDocChange={onChatDocChange}
              onFieldUpdates={applyChatFieldUpdates}
              history={chatHistory}
              onHistoryChange={setChatHistory}
            />
          ) : (
            <div className="card p-5">
              {manifest !== null ? (
                <DocForm
                  locale={locale}
                  manifest={manifest}
                  values={displayGenericFields}
                  fieldStates={draftState?.fields}
                  onConfirm={confirmField}
                  onReject={rejectField}
                />
              ) : null}
            </div>
          )}
          <p className="mt-3 text-xs" style={{ color: "var(--ink-3)" }}>
            {t.printHint}
          </p>
          {downloadBlockedLabels.length > 0 && (
            <div
              role="alert"
              className="mt-3 rounded border px-3 py-2 text-sm"
              style={{
                borderColor: "#b85c00",
                background: "#fff7ed",
                color: "#7a3400",
              }}
            >
              <p className="font-medium">{t.downloadBlockedFields}</p>
              <ul className="mt-1 list-disc pl-5">
                {downloadBlockedLabels.map((label) => (
                  <li key={label}>{label}</li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <div>
          <Disclaimer locale={locale} variant="banner" />
          <GenericDocPreview
            load={templateLoad}
            fields={genericFields}
            draftState={draftState}
            locale={locale}
          />
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
      className="mode-tab"
    >
      {label}
    </button>
  );
}
