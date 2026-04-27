import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem(
      "prelegal:session",
      JSON.stringify({
        user: {
          id: 1,
          email: "e2e@example.com",
          name: "",
          created_at: "2026-04-25T00:00:00",
        },
        token: "e2e-token",
      }),
    );
  });
  // Stub the documents list/CRUD — the home page calls it on mount and
  // auto-saves on edit; without these the dev server would 404 and we'd
  // 401-bounce.
  const stubDoc = {
    id: 1,
    doc_id: "mutual-nda",
    title: "draft",
    state: {},
    created_at: "2026-04-27T00:00:00",
    updated_at: "2026-04-27T00:00:00",
  };
  await page.route("**/api/documents", (route) => {
    if (route.request().method() === "GET") {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      });
    } else if (route.request().method() === "POST") {
      route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(stubDoc),
      });
    } else {
      route.continue();
    }
  });
  await page.route(/\/api\/documents\/\d+$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(stubDoc),
    }),
  );
});

test.describe("MNDA chat", () => {
  test("chat tab is the default editor and shows the welcome message", async ({
    page,
  }) => {
    await page.goto("/");
    // Welcome bubble (Chinese) is rendered into the chat panel — opens the
    // multi-doc picker rather than assuming MNDA.
    await expect(page.getByText(/起草一份法律协议/)).toBeVisible();
    // English welcome appears after switching language.
    await page.getByRole("button", { name: "English" }).click();
    await expect(page.getByText(/draft a legal agreement/i)).toBeVisible();
  });

  test("sending a chat turn updates the preview through the merged state", async ({
    page,
  }) => {
    // Stub /api/chat — the dev server doesn't run the backend.
    await page.route("**/api/chat", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          assistant_message: "Got it. Anything else to tweak?",
          mnda_updates: { governingLaw: "California" },
          done: false,
        }),
      }),
    );

    await page.goto("/");
    await page.getByRole("button", { name: "English" }).click();

    await page
      .getByLabel(/Type a message/i)
      .fill("Use California governing law.");
    await page.getByRole("button", { name: /^Send$/ }).click();

    await expect(
      page.getByText(/Got it. Anything else to tweak/),
    ).toBeVisible();
    // Preview reflects the merged state.
    await expect(page.locator("[data-print-root]")).toContainText("California");
  });

  test("focuses the input on load and returns focus after a turn", async ({
    page,
  }) => {
    await page.route("**/api/chat", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          assistant_message: "Got it. Anything else?",
          mnda_updates: {},
          done: false,
        }),
      }),
    );

    await page.goto("/");

    // Focused on initial render (before any user interaction can steal focus)
    // — the user can start typing immediately after landing on /.
    const zhInput = page.getByLabel(/输入消息/);
    await expect(zhInput).toBeFocused();

    await page.getByRole("button", { name: "English" }).click();

    const input = page.getByLabel(/Type a message/i);
    await input.fill("Hi");
    await page.getByRole("button", { name: /^Send$/ }).click();

    // After the click moves focus to the button, the chat must restore
    // focus to the input once the turn completes.
    await expect(page.getByText(/Got it\. Anything else/)).toBeVisible();
    await expect(input).toBeFocused();
  });

  test("switches to a non-MNDA doc preview when the LLM picks one", async ({
    page,
  }) => {
    await page.route("**/api/chat", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          assistant_message: "Got it — drafting a CSA. Who's the customer?",
          selected_doc_id: "cloud-service-agreement",
          mnda_updates: {},
          field_updates: { Customer: "Acme" },
          done: false,
        }),
      }),
    );
    // Mock the template endpoint too — the dev server doesn't run the backend.
    await page.route("**/api/templates/cloud-service-agreement", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          doc_id: "cloud-service-agreement",
          title: "Cloud Service Agreement (CSA)",
          standard_terms: "# Cloud Service Agreement\n\nThis is a stub.",
          cover_page: null,
        }),
      }),
    );

    await page.goto("/");
    await page.getByRole("button", { name: "English" }).click();

    await page.getByLabel(/Type a message/i).fill("Draft a CSA for me.");
    await page.getByRole("button", { name: /^Send$/ }).click();

    // Header now reflects the new doc.
    await expect(page.getByText(/Drafting:/)).toContainText(
      "Cloud Service Agreement",
    );
    // The generic preview rendered the fetched template title (with the
    // catalog title format including the abbreviation in parentheses) and
    // the AI-collected Cover Page Summary.
    await expect(
      page.getByRole("heading", {
        name: "Cloud Service Agreement (CSA)",
        level: 1,
      }),
    ).toBeVisible();
    await expect(page.getByText("Cover Page Summary")).toBeVisible();
    await expect(page.getByText("Acme")).toBeVisible();
    // The manual-edit form tab is hidden for non-MNDA docs.
    await expect(
      page.getByRole("tab", { name: /Edit fields/ }),
    ).toHaveCount(0);
  });

  test("chat error from the API surfaces inline", async ({ page }) => {
    await page.route("**/api/chat", (route) =>
      route.fulfill({
        status: 502,
        contentType: "application/json",
        body: JSON.stringify({ detail: "OPENROUTER_API_KEY is not set." }),
      }),
    );

    await page.goto("/");
    await page.getByRole("button", { name: "English" }).click();

    await page.getByLabel(/Type a message/i).fill("hello");
    await page.getByRole("button", { name: /^Send$/ }).click();

    // Multiple role="alert" elements exist (one is Next's route announcer);
    // assert against the visible inline error specifically.
    await expect(
      page.getByText("OPENROUTER_API_KEY is not set."),
    ).toBeVisible();
  });
});
