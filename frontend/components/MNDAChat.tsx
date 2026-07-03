"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, chatApi, type ChatTurn } from "@/lib/api";
import type { Locale } from "@/lib/i18n";
import { useDictionary } from "@/lib/i18n";
import {
  mergeMndaUpdates,
  type MndaState,
} from "@/lib/mndaState";
import { clearSession, readToken } from "@/lib/session";

type Props = {
  locale: Locale;
  state: MndaState;
  // Returns the page-level draft generation. Captured when a chat request
  // starts; if it changed by the time the response arrives, the user has
  // switched drafts and the response must be discarded — applying it would
  // merge one draft's conversation into another and the debounced auto-save
  // would persist the corruption.
  getDraftEpoch: () => number;
  // Accept either a value or an updater. When an LLM response arrives after
  // an unrelated re-render (e.g., user switched to the form tab and edited
  // a field), the updater form merges against the freshest state instead of
  // a stale snapshot.
  onStateChange: (next: MndaState | ((prev: MndaState) => MndaState)) => void;
  // Called when the LLM picks (or switches) the target document. Empty
  // string until intent is clear.
  onDocChange: (docId: string) => void;
  // Called when the LLM extracts cover-page-level fields for non-MNDA docs.
  onFieldUpdates: (updates: Record<string, string>) => void;
  // Conversation history is owned by the page so it can be auto-saved
  // and restored alongside the rest of the document state. Empty array
  // means "fresh chat" — we render a localized welcome bubble in its
  // place rather than persisting that bubble as part of history.
  history: ChatTurn[];
  onHistoryChange: (next: ChatTurn[]) => void;
};

/**
 * Chat panel that drives the MNDA via free-form conversation.
 *
 * History is a controlled prop owned by the page so it travels with the
 * saved draft (see app/page.tsx). The first assistant turn is rendered
 * lazily from the i18n dict whenever history is empty; that way the
 * welcome bubble follows the current locale and never gets persisted to
 * the DB on its own.
 */
export function MNDAChat({
  locale,
  state,
  getDraftEpoch,
  onStateChange,
  onDocChange,
  onFieldUpdates,
  history,
  onHistoryChange,
}: Props) {
  const t = useDictionary(locale);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Focus the input on first mount so the user can start typing immediately
  // after landing on the chat tab.
  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  useEffect(() => {
    // Pin the scroll to the bottom whenever a new message arrives.
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [history, sending]);

  const send = async () => {
    const content = draft.trim();
    if (!content || sending) return;

    const userTurn: ChatTurn = { role: "user", content };
    const nextHistory = [...history, userTurn];
    onHistoryChange(nextHistory);
    setDraft("");
    setError(null);
    setSending(true);
    const epochAtSend = getDraftEpoch();

    try {
      const res = await chatApi.send(
        readToken(),
        nextHistory,
        state as unknown as Record<string, unknown>,
      );
      if (getDraftEpoch() !== epochAtSend) {
        // The user switched to another draft while this request was in
        // flight. Everything below writes into page-level state that now
        // belongs to the other draft — drop the response instead.
        return;
      }
      onStateChange((prev) => mergeMndaUpdates(prev, res.mnda_updates));
      // The LLM may leave selected_doc_id empty when it isn't yet sure what
      // the user wants — only propagate non-empty values so we don't reset
      // a doc the user already locked in.
      if (res.selected_doc_id) onDocChange(res.selected_doc_id);
      if (res.field_updates && Object.keys(res.field_updates).length > 0) {
        onFieldUpdates(res.field_updates);
      }
      onHistoryChange([
        ...nextHistory,
        { role: "assistant", content: res.assistant_message },
      ]);
      if (res.done) setDone(true);
    } catch (err) {
      // A late failure from a draft the user already left is noise — the
      // message it complains about isn't on screen anymore.
      if (getDraftEpoch() !== epochAtSend) return;
      // Chat is a protected endpoint now — an expired/invalid session gets
      // the same treatment as everywhere else: clear it and go to /login.
      if (err instanceof ApiError && err.status === 401) {
        clearSession();
        window.location.replace("/login");
        return;
      }
      // Don't roll the user message out of history — they should see what
      // they sent and have the chance to retry.
      const message =
        err instanceof ApiError && err.message ? err.message : t.chat.error;
      setError(message);
    } finally {
      setSending(false);
      // Send focus back to the input so the user can keep typing without
      // reaching for the mouse — applies whether the turn succeeded, errored,
      // or completed the MNDA (they may still want to ask questions).
      textareaRef.current?.focus();
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  };

  return (
    <div className="flex h-[calc(100vh-12rem)] flex-col rounded-lg border border-neutral-200 bg-white shadow-sm">
      <div
        ref={scrollRef}
        className="flex-1 space-y-3 overflow-y-auto px-4 py-3"
      >
        {history.length === 0 && (
          <Bubble role="assistant">{t.chat.welcome}</Bubble>
        )}
        {history.map((turn, i) => (
          <Bubble key={i} role={turn.role}>
            {turn.content}
          </Bubble>
        ))}
        {sending && (
          <Bubble role="assistant">
            <span className="italic" style={{ color: "#888888" }}>
              …
            </span>
          </Bubble>
        )}
      </div>

      {done && (
        <div
          className="border-t border-neutral-200 px-4 py-2 text-sm"
          style={{ color: "#032147", background: "#fef9e7" }}
        >
          {t.chat.doneBanner}
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="border-t border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700"
        >
          <span className="font-medium">⚠ </span>
          {error}
        </div>
      )}

      <div className="border-t border-neutral-200 p-3">
        <div className="flex items-end gap-2">
          <textarea
            ref={textareaRef}
            className="min-h-[44px] flex-1 resize-y rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm shadow-sm focus:outline-none"
            rows={2}
            placeholder={t.chat.placeholder}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            aria-label={t.chat.placeholder}
          />
          <button
            type="button"
            onClick={() => void send()}
            disabled={sending || !draft.trim()}
            className="shrink-0 rounded-md px-4 py-2 text-sm font-medium text-white shadow-sm disabled:opacity-50"
            style={{ backgroundColor: "#753991" }}
          >
            {sending ? t.chat.sending : t.chat.send}
          </button>
        </div>
      </div>
    </div>
  );
}

function Bubble({
  role,
  children,
}: {
  role: ChatTurn["role"];
  children: React.ReactNode;
}) {
  const isUser = role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className="max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm"
        style={
          isUser
            ? { background: "#209dd7", color: "white" }
            : { background: "#f3f4f6", color: "#032147" }
        }
      >
        {children}
      </div>
    </div>
  );
}
