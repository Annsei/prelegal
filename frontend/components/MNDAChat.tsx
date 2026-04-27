"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, chatApi, type ChatTurn } from "@/lib/api";
import type { Locale } from "@/lib/i18n";
import { useDictionary } from "@/lib/i18n";
import {
  mergeMndaUpdates,
  type MndaState,
} from "@/lib/mndaState";

type Props = {
  locale: Locale;
  state: MndaState;
  // Accept either a value or an updater. When an LLM response arrives after
  // an unrelated re-render (e.g., user switched to the form tab and edited
  // a field), the updater form merges against the freshest state instead of
  // a stale snapshot.
  onStateChange: (next: MndaState | ((prev: MndaState) => MndaState)) => void;
};

/**
 * Chat panel that drives the MNDA via free-form conversation.
 *
 * State is held client-side: we keep the full message history in memory and
 * POST it on each turn (the backend is stateless). The first assistant turn
 * is a static welcome string from the i18n dict so the user gets immediate
 * feedback without an LLM round-trip.
 */
export function MNDAChat({ locale, state, onStateChange }: Props) {
  const t = useDictionary(locale);
  const [history, setHistory] = useState<ChatTurn[]>([
    { role: "assistant", content: t.chat.welcome },
  ]);
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

  // Re-localize the static welcome message when the user toggles language —
  // but only if it's still the first turn (otherwise we'd rewrite history).
  useEffect(() => {
    setHistory((prev) => {
      if (prev.length !== 1 || prev[0].role !== "assistant") return prev;
      return [{ role: "assistant", content: t.chat.welcome }];
    });
  }, [t.chat.welcome]);

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
    setHistory(nextHistory);
    setDraft("");
    setError(null);
    setSending(true);

    try {
      const res = await chatApi.send(
        nextHistory,
        state as unknown as Record<string, unknown>,
      );
      onStateChange((prev) => mergeMndaUpdates(prev, res.mnda_updates));
      setHistory([
        ...nextHistory,
        { role: "assistant", content: res.assistant_message },
      ]);
      if (res.done) setDone(true);
    } catch (err) {
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
          className="border-t border-neutral-200 px-4 py-2 text-sm text-red-600"
        >
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
