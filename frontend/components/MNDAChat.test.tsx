import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MNDAChat } from "./MNDAChat";
import { INITIAL_STATE, type MndaState } from "@/lib/mndaState";

function Harness({
  locale = "en" as "en" | "zh",
  onDocChange = () => {},
  onFieldUpdates = () => {},
}: {
  locale?: "en" | "zh";
  onDocChange?: (id: string) => void;
  onFieldUpdates?: (updates: Record<string, string>) => void;
}) {
  const [state, setState] = useState<MndaState>(INITIAL_STATE);
  return (
    <>
      <div data-testid="state-json">{JSON.stringify(state)}</div>
      <MNDAChat
        locale={locale}
        state={state}
        onStateChange={setState}
        onDocChange={onDocChange}
        onFieldUpdates={onFieldUpdates}
      />
    </>
  );
}

function currentState(): MndaState {
  return JSON.parse(screen.getByTestId("state-json").textContent ?? "{}");
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

  it("sends a turn, appends the assistant reply, and merges field updates", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          assistant_message: "Got it. What's the effective date?",
          mnda_updates: { purpose: "Evaluating a partnership" },
          done: false,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<Harness locale="en" />);
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
    // Field merged into shared state.
    expect(currentState().purpose).toBe("Evaluating a partnership");
    // The user's message is preserved in the chat regardless.
    expect(
      screen.getByText("We're evaluating a partnership."),
    ).toBeInTheDocument();

    // The request payload should carry both history and current state.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const init = fetchMock.mock.calls[0][1];
    const body = JSON.parse(init.body as string);
    expect(body.messages.at(-1)).toEqual({
      role: "user",
      content: "We're evaluating a partnership.",
    });
    expect(body.mnda_state).toMatchObject({ purpose: expect.any(String) });
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
    expect(onFieldUpdates).toHaveBeenCalledWith({
      Customer: "Acme",
      Provider: "Globex",
    });
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
