import { expect, test } from "@playwright/test";

const MNDA_TEMPLATE = {
  doc_id: "mutual-nda",
  title: "双方保密协议",
  cover_page:
    '# 双方保密协议 · 封面页\n\n<span class="coverpage_link">保密用途</span>',
  standard_terms:
    '# 双方保密协议 · 标准条款\n\n<span class="coverpage_link">保密用途</span>',
  manifest: {
    doc_id: "mutual-nda",
    version: 1,
    sections: [{ key: "keyterms", label: { zh: "关键条款", en: "Key Terms" } }],
    fields: [
      {
        key: "保密用途",
        section: "keyterms",
        type: "text",
        required: true,
        label: { zh: "保密用途", en: "Confidential Purpose" },
      },
    ],
  },
};

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
  await page.route(/\/api\/documents\/\d+\/field-patches$/, async (route) => {
    const body = (await route.request().postDataJSON()) as {
      operations: Array<{ key: string; value?: string }>;
    };
    const fields = Object.fromEntries(
      MNDA_TEMPLATE.manifest.fields.map((field) => [
        field.key,
        {
          key: field.key,
          status: "missing",
          value: null,
          revision: 0,
          provenance: [],
        },
      ]),
    );
    for (const operation of body.operations) {
      fields[operation.key] = {
        key: operation.key,
        status: "pending_confirmation",
        value: operation.value ?? "",
        revision: 1,
        provenance: [],
      };
    }
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        snapshot: {
          schema_version: "draft-state.v1",
          manifest_version: 1,
          doc_id: "mutual-nda",
          revision: 1,
          fields,
          validation_errors: [],
          applied_patches: {},
        },
        duplicate: false,
      }),
    });
  });
  await page.route("**/api/templates/mutual-nda", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MNDA_TEMPLATE),
    }),
  );
});

test.describe("Document chat", () => {
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

  test("sending a chat turn updates the preview through kernel pending state", async ({
    page,
  }) => {
    // Stub /api/chat — the dev server doesn't run the backend.
    await page.route("**/api/chat", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          assistant_message: "Got it. Anything else to tweak?",
          selected_doc_id: "mutual-nda",
          mnda_updates: {},
          field_updates: { 保密用途: "评估加州合作" },
          done: false,
        }),
      }),
    );

    await page.goto("/");
    await page.getByRole("button", { name: "English" }).click();

    await page
      .getByLabel(/Type a message/i)
      .fill("Use this NDA to evaluate a California partnership.");
    await page.getByRole("button", { name: /^Send$/ }).click();

    await expect(
      page.getByText(/Got it. Anything else to tweak/),
    ).toBeVisible();
    // Preview reflects the kernel field update as pending state.
    await expect(page.locator("[data-print-root]")).toContainText("评估加州合作");
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
          selected_doc_id: "pilot-agreement",
          mnda_updates: {},
          field_updates: { Customer: "Acme" },
          done: false,
        }),
      }),
    );
    // Mock the template endpoint too — the dev server doesn't run the backend.
    await page.route("**/api/templates/pilot-agreement", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          doc_id: "pilot-agreement",
          title: "Pilot Agreement",
          standard_terms: "# Pilot Agreement\n\nThis is a stub.",
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
      "Pilot Agreement",
    );
    // The generic preview rendered the fetched template title (with the
    // catalog title format including the abbreviation in parentheses) and
    // the AI-collected Cover Page Summary.
    await expect(
      page.getByRole("heading", {
        name: "Pilot Agreement",
        level: 1,
      }).first(),
    ).toBeVisible();
    await expect(page.getByText("Cover Page Summary")).toBeVisible();
    await expect(page.getByText("Acme")).toBeVisible();
    // Fallback docs without manifests do not expose the manual-edit form tab.
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
