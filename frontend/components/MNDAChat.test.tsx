import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MNDAChat } from "./MNDAChat";
import type { ChatTurn } from "@/lib/api";

function Harness({
  locale = "en" as "en" | "zh",
  docId = "mutual-nda",
  fields = {},
  onDocChange = () => {},
  onFieldUpdates = () => {},
  initialHistory = [] as ChatTurn[],
  getDraftEpoch = () => 0,
}: {
  locale?: "en" | "zh";
  docId?: string;
  fields?: Record<string, string>;
  onDocChange?: (id: string) => void;
  onFieldUpdates?: (
    updates: Record<string, string>,
    context: {
      docId: string;
      history: ChatTurn[];
      messageIndex: number;
    },
  ) => void | Promise<void>;
  initialHistory?: ChatTurn[];
  getDraftEpoch?: () => number;
}) {
  const [history, setHistory] = useState<ChatTurn[]>(initialHistory);
  return (
    <MNDAChat
      locale={locale}
      fields={fields}
      docId={docId}
      getDraftEpoch={getDraftEpoch}
      onDocChange={onDocChange}
      onFieldUpdates={onFieldUpdates}
      history={history}
      onHistoryChange={setHistory}
    />
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("MNDAChat", () => {
  it("renders the static welcome message in the active locale", () => {
    render(<Harness locale="en" />);
    expect(screen.getByText(/draft a legal agreement/i)).toBeInTheDocument();
  });

  it("hides the welcome and replays prior history when one is provided", () => {
    const restored: ChatTurn[] = [
      { role: "user", content: "Earlier user message" },
      { role: "assistant", content: "Earlier assistant reply" },
    ];
    render(<Harness locale="en" initialHistory={restored} />);
    // Replayed turns visible.
    expect(screen.getByText("Earlier user message")).toBeInTheDocument();
    expect(screen.getByText("Earlier assistant reply")).toBeInTheDocument();
    // Welcome bubble suppressed when history isn't empty.
    expect(screen.queryByText(/draft a legal agreement/i)).toBeNull();
  });

  it("renders assistant newlines with pre-wrapped whitespace", () => {
    render(
      <Harness
        locale="en"
        initialHistory={[
          { role: "assistant", content: "First line\nSecond line" },
        ]}
      />,
    );

    const bubble = screen.getByText(/First line/);
    expect(bubble).toHaveClass("whitespace-pre-wrap");
    expect(bubble).toHaveClass("chat-bubble-assistant");
    expect(bubble.textContent).toBe("First line\nSecond line");
  });

  it("sends a turn, appends the assistant reply, and forwards MNDA field updates", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          assistant_message: "Got it. What's the effective date?",
          mnda_updates: { purpose: "must be ignored" },
          field_updates: { "保密用途": "Evaluating a partnership" },
          done: false,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const onFieldUpdates = vi.fn();
    render(<Harness locale="en" onFieldUpdates={onFieldUpdates} />);
    await userEvent.type(
      screen.getByLabelText(/type a message/i),
      "We're evaluating a partnership.",
    );
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    // Assistant reply rendered.
    await waitFor(() =>
      expect(
        screen.getByText(/What's the effective date/i),
      ).toBeInTheDocument(),
    );
    expect(onFieldUpdates).toHaveBeenCalledWith(
      { "保密用途": "Evaluating a partnership" },
      expect.objectContaining({
        docId: "mutual-nda",
        messageIndex: 0,
      }),
    );
    // The user's message is preserved in the chat regardless.
    expect(
      screen.getByText("We're evaluating a partnership."),
    ).toBeInTheDocument();
    expect(screen.getByText("We're evaluating a partnership.")).toHaveClass(
      "chat-bubble-user",
    );

    // The request payload should carry both history and current state.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const init = fetchMock.mock.calls[0][1];
    const body = JSON.parse(init.body as string);
    expect(body.messages.at(-1)).toEqual({
      role: "user",
      content: "We're evaluating a partnership.",
    });
    expect(body.mnda_state).toEqual({});
    expect(body.document_state).toMatchObject({
      doc_id: "mutual-nda",
      fields: {},
    });
    // The open doc travels with every turn so the backend can inject its
    // cover-page field checklist.
    expect(body.doc_id).toBe("mutual-nda");
  });

  it("sends manifest document fields as the unified current state", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          assistant_message: "还需要服务费是多少？",
          selected_doc_id: "cloud-service-agreement",
          mnda_updates: {},
          field_updates: {},
          done: false,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(
      <Harness
        locale="zh"
        docId="cloud-service-agreement"
        fields={{ 客户: "示例科技", 订阅期: "12 个月" }}
      />,
    );
    await userEvent.type(screen.getByLabelText(/输入消息/), "服务方是云服务商");
    await userEvent.click(screen.getByRole("button", { name: /发送/ }));

    await waitFor(() =>
      expect(screen.getByText(/服务费是多少/)).toBeInTheDocument(),
    );

    const init = fetchMock.mock.calls[0][1];
    const body = JSON.parse(init.body as string);
    expect(body.document_state).toMatchObject({
      doc_id: "cloud-service-agreement",
      fields: { 客户: "示例科技", 订阅期: "12 个月" },
    });
  });

  it("shows an error message when the chat API fails and keeps the user turn visible", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ detail: "OPENROUTER_API_KEY is not set." }),
        { status: 502, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<Harness locale="en" />);
    await userEvent.type(screen.getByLabelText(/type a message/i), "hi");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/OPENROUTER_API_KEY/),
    );
    expect(screen.getByText("hi")).toBeInTheDocument();
  });

  it("forwards selected_doc_id and field_updates from the chat response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          assistant_message: "Got it. Anything else?",
          selected_doc_id: "cloud-service-agreement",
          mnda_updates: {},
          field_updates: { Customer: "Acme", Provider: "Globex" },
          done: false,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const onDocChange = vi.fn();
    const onFieldUpdates = vi.fn();
    render(
      <Harness
        locale="en"
        onDocChange={onDocChange}
        onFieldUpdates={onFieldUpdates}
      />,
    );

    await userEvent.type(
      screen.getByLabelText(/type a message/i),
      "I want a CSA, Acme is the customer.",
    );
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() =>
      expect(onDocChange).toHaveBeenCalledWith("cloud-service-agreement"),
    );
    expect(onFieldUpdates).toHaveBeenCalledWith(
      {
        Customer: "Acme",
        Provider: "Globex",
      },
      expect.objectContaining({
        docId: "cloud-service-agreement",
        messageIndex: 0,
      }),
    );
  });

  it("does not call onDocChange when selected_doc_id is empty", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          assistant_message: "Which document?",
          selected_doc_id: "",
          mnda_updates: {},
          field_updates: {},
          done: false,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const onDocChange = vi.fn();
    render(<Harness locale="en" onDocChange={onDocChange} />);

    await userEvent.type(screen.getByLabelText(/type a message/i), "hi");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() =>
      expect(screen.getByText(/Which document/)).toBeInTheDocument(),
    );
    expect(onDocChange).not.toHaveBeenCalled();
  });

  it("focuses the input on mount and returns focus to it after sending", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          assistant_message: "What's the effective date?",
          mnda_updates: {},
          done: false,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<Harness locale="en" />);
    const input = screen.getByLabelText(/type a message/i);
    // Focused on first mount — the user can start typing without clicking.
    expect(input).toHaveFocus();

    // Send a message; focus should land back on the input afterwards so the
    // user can keep typing without reaching for the mouse.
    await userEvent.type(input, "We're evaluating a partnership.");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() =>
      expect(
        screen.getByText(/What's the effective date/i),
      ).toBeInTheDocument(),
    );
    expect(input).toHaveFocus();
  });

  it("discards a response that arrives after the draft epoch changed", async () => {
    // Simulates: user sends a message in draft A, switches to draft B while
    // the request is in flight, then the reply arrives. Nothing from that
    // reply may be applied — otherwise auto-save would persist A's turn
    // into B's row.
    let resolveFetch: (r: Response) => void = () => {};
    const fetchMock = vi.fn().mockReturnValue(
      new Promise<Response>((resolve) => {
        resolveFetch = resolve;
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    let epoch = 0;
    const onDocChange = vi.fn();
    const onFieldUpdates = vi.fn();
    render(
      <Harness
        locale="en"
        getDraftEpoch={() => epoch}
        onDocChange={onDocChange}
        onFieldUpdates={onFieldUpdates}
      />,
    );

    await userEvent.type(screen.getByLabelText(/type a message/i), "hello");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    // The draft switches while the request is pending.
    epoch = 1;
    resolveFetch(
      new Response(
        JSON.stringify({
          assistant_message: "Stale reply that must not render",
          selected_doc_id: "cloud-service-agreement",
          mnda_updates: { purpose: "stale purpose" },
          field_updates: { Customer: "Stale Corp" },
          done: false,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    // Sending indicator clears once the (discarded) response settles —
    // the button label flips back from "Sending…" to "Send".
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /^send$/i }),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByText(/Stale reply that must not render/),
    ).toBeNull();
    expect(onDocChange).not.toHaveBeenCalled();
    expect(onFieldUpdates).not.toHaveBeenCalled();
  });

  it("shows the done banner when the API reports done: true", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          assistant_message: "All set!",
          mnda_updates: {},
          done: true,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<Harness locale="en" />);
    await userEvent.type(
      screen.getByLabelText(/type a message/i),
      "looks good",
    );
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() =>
      expect(screen.getByText(/MNDA is ready/i)).toBeInTheDocument(),
    );
  });
});
