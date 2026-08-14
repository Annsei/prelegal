"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, chatApi, type ChatTurn } from "@/lib/api";
import type { Locale } from "@/lib/i18n";
import { useDictionary } from "@/lib/i18n";
import { clearSession, readToken } from "@/lib/session";

type Props = {
  locale: Locale;
  fields: Record<string, string>;
  // The catalog doc currently open. Sent with each chat turn so the
  // backend can inject that document's cover-page field checklist into
  // the LLM prompt (see backend/app/manifests.py).
  docId: string;
  // Returns the page-level draft generation. Captured when a chat request
  // starts; if it changed by the time the response arrives, the user has
  // switched drafts and the response must be discarded — applying it would
  // merge one draft's conversation into another and the debounced auto-save
  // would persist the corruption.
  getDraftEpoch: () => number;
  // Called when the LLM picks (or switches) the target document. Empty
  // string until intent is clear.
  onDocChange: (docId: string) => void;
  // Called when the LLM extracts cover-page-level fields. Manifest documents
  // turn these into server-owned field-patch proposals; fallback documents
  // still use flat fields.
  onFieldUpdates: (
    updates: Record<string, string>,
    context: {
      docId: string;
      history: ChatTurn[];
      messageIndex: number;
    },
  ) => void | Promise<void>;
  // Conversation history is owned by the page so it can be auto-saved
  // and restored alongside the rest of the document state. Empty array
  // means "fresh chat" — we render a localized welcome bubble in its
  // place rather than persisting that bubble as part of history.
  history: ChatTurn[];
  onHistoryChange: (next: ChatTurn[]) => void;
};

/**
 * Chat panel for the currently selected document.
 *
 * History is a controlled prop owned by the page so it travels with the
 * saved draft (see app/page.tsx). The first assistant turn is rendered
 * lazily from the i18n dict whenever history is empty; that way the
 * welcome bubble follows the current locale and never gets persisted to
 * the DB on its own.
 */
export function MNDAChat({
  locale,
  fields,
  docId,
  getDraftEpoch,
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
        {},
        docId,
        {
          doc_id: docId,
          fields,
        },
      );
      if (getDraftEpoch() !== epochAtSend) {
        // The user switched to another draft while this request was in
        // flight. Everything below writes into page-level state that now
        // belongs to the other draft — drop the response instead.
        return;
      }
      // The LLM may leave selected_doc_id empty when it isn't yet sure what
      // the user wants — only propagate non-empty values so we don't reset
      // a doc the user already locked in.
      const targetDocId = res.selected_doc_id || docId;
      if (res.selected_doc_id) onDocChange(res.selected_doc_id);
      const completeHistory = [
        ...nextHistory,
        { role: "assistant" as const, content: res.assistant_message },
      ];
      if (res.field_updates && Object.keys(res.field_updates).length > 0) {
        await onFieldUpdates(res.field_updates, {
          docId: targetDocId,
          history: completeHistory,
          messageIndex: nextHistory.length - 1,
        });
      }
      onHistoryChange(completeHistory);
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

  const sendLabel = sending ? t.chat.sending : t.chat.send;

  return (
    <div className="chat-panel flex flex-col overflow-hidden">
      <div
        ref={scrollRef}
        className="chat-scroll flex-1 space-y-4 overflow-y-auto px-4 py-5"
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
            <span className="typing-dots" aria-hidden>
              <i />
              <i />
              <i />
            </span>
            <span className="sr-only">{t.chat.sending}</span>
          </Bubble>
        )}
      </div>

      {done && (
        <div
          className="border-t px-4 py-2 text-sm"
          style={{
            color: "var(--ink)",
            background: "var(--gold-soft)",
            borderColor: "var(--rule-soft)",
          }}
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

      <div className="chat-composer border-t p-3">
        <div className="chat-composer-row">
          <textarea
            ref={textareaRef}
            className="input-field chat-composer-input min-h-[52px] flex-1 resize-y"
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
            className="chat-send-btn"
            aria-label={sendLabel}
          >
            <span className="sr-only">{sendLabel}</span>
            <svg
              aria-hidden="true"
              viewBox="0 0 24 24"
              className="chat-send-icon"
            >
              <path
                fill="currentColor"
                d="M3.4 20.6 21 12 3.4 3.4 3 10l11 2-11 2z"
              />
            </svg>
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
    <div className={`bubble flex ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser && (
        <span className="chat-avatar" aria-hidden="true">
          契
        </span>
      )}
      <div
        className={`chat-bubble max-w-[85%] whitespace-pre-wrap px-3.5 py-2.5 text-sm leading-relaxed ${
          isUser ? "chat-bubble-user" : "chat-bubble-assistant"
        }`}
      >
        {children}
      </div>
    </div>
  );
}
