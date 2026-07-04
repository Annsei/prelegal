import { expect, test } from "@playwright/test";

const SESSION_KEY = "prelegal:session";

test.beforeEach(async ({ page }) => {
  await page.addInitScript((key) => {
    window.localStorage.setItem(
      key,
      JSON.stringify({
        user: {
          id: 1,
          email: "docs@example.com",
          name: "",
          created_at: "2026-04-25T00:00:00",
        },
        token: "docs-token",
      }),
    );
  }, SESSION_KEY);
});

test.describe("Documents — sidebar and auto-save", () => {
  test("sidebar shows existing drafts and renders the disclaimer", async ({
    page,
  }) => {
    await page.route("**/api/documents", (route) => {
      if (route.request().method() === "GET") {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: 7,
              doc_id: "mutual-nda",
              title: "Acme × Globex MNDA",
              created_at: "2026-04-27T01:00:00",
              updated_at: "2026-04-27T02:00:00",
            },
            {
              id: 8,
              doc_id: "cloud-service-agreement",
              title: "Beta CSA",
              created_at: "2026-04-27T03:00:00",
              updated_at: "2026-04-27T04:00:00",
            },
          ]),
        });
      } else {
        route.continue();
      }
    });

    await page.goto("/");

    // Both drafts are listed in the sidebar.
    await expect(page.getByText("Acme × Globex MNDA")).toBeVisible();
    await expect(page.getByText("Beta CSA")).toBeVisible();
    // Catalog title appears under each draft as the secondary line — the
    // default locale is zh so the rendered string is the Chinese label.
    await expect(page.getByText("双方保密协议（MNDA）").first()).toBeVisible();

    // Disclaimer banner above the preview (note the warning prefix).
    await expect(page.getByRole("note")).toContainText(/AI 生成的草稿|AI-generated draft/);
    // Footer disclaimer.
    await expect(
      page.locator("footer").getByText(/草稿|draft/i),
    ).toBeVisible();
  });

  test("typing a chat turn triggers a debounced auto-save with bearer token", async ({
    page,
  }) => {
    let listCalls = 0;
    let postCalls = 0;
    let putCalls = 0;
    let lastAuth = "";

    await page.route("**/api/documents", (route) => {
      const method = route.request().method();
      lastAuth = route.request().headers()["authorization"] ?? "";
      if (method === "GET") {
        listCalls += 1;
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: "[]",
        });
      } else if (method === "POST") {
        postCalls += 1;
        route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            id: 99,
            doc_id: "mutual-nda",
            title: "draft",
            state: {},
            created_at: "2026-04-27T00:00:00",
            updated_at: "2026-04-27T00:00:00",
          }),
        });
      } else {
        route.continue();
      }
    });
    await page.route(/\/api\/documents\/\d+$/, (route) => {
      putCalls += 1;
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: 99,
          doc_id: "mutual-nda",
          title: "Acme MNDA",
          state: {},
          created_at: "2026-04-27T00:00:00",
          updated_at: "2026-04-27T00:00:01",
        }),
      });
    });
    await page.route("**/api/chat", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          assistant_message: "Got it. Anything else?",
          selected_doc_id: "mutual-nda",
          mnda_updates: {
            party1: { company: "Acme", signerName: "", signerTitle: "", noticeAddress: "" },
          },
          field_updates: {},
          done: false,
        }),
      }),
    );

    await page.goto("/");
    await page.getByRole("button", { name: "English" }).click();

    await page
      .getByLabel(/Type a message/i)
      .fill("Acme is party 1, please.");
    await page.getByRole("button", { name: /^Send$/ }).click();

    // Save status appears once the debounce fires.
    await expect(page.getByText("Saved")).toBeVisible({ timeout: 5000 });
    expect(postCalls + putCalls).toBeGreaterThan(0);
    expect(lastAuth).toBe("Bearer docs-token");
    // The list refresh after save means we hit GET more than once.
    expect(listCalls).toBeGreaterThanOrEqual(2);
  });

  test("chat history is restored after a page refresh", async ({ page }) => {
    // Saved draft already contains a back-and-forth — `state` carries
    // both `chat` (the conversation) and `mnda` (typed fields).
    const docId = 42;
    const savedDoc = {
      id: docId,
      doc_id: "mutual-nda",
      title: "Acme × Globex MNDA",
      state: {
        chat: [
          { role: "user", content: "Use Acme as party 1." },
          { role: "assistant", content: "Got it. Who is party 2?" },
        ],
        mnda: {
          party1: { company: "Acme", signerName: "", signerTitle: "", noticeAddress: "" },
        },
      },
      created_at: "2026-04-27T00:00:00",
      updated_at: "2026-04-27T01:00:00",
    };

    await page.route("**/api/documents", (route) => {
      if (route.request().method() === "GET") {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: docId,
              doc_id: savedDoc.doc_id,
              title: savedDoc.title,
              created_at: savedDoc.created_at,
              updated_at: savedDoc.updated_at,
            },
          ]),
        });
      } else {
        route.continue();
      }
    });
    await page.route(new RegExp(`/api/documents/${docId}$`), (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(savedDoc),
      }),
    );

    // Plant the "last active doc id" pointer that page.tsx reads on
    // mount — same shape the app writes there itself.
    await page.addInitScript(({ key, id }) => {
      window.localStorage.setItem(key, String(id));
    }, { key: "prelegal:activeDocId", id: docId });

    await page.goto("/");
    await page.getByRole("button", { name: "English" }).click();

    // Both turns from the saved chat are replayed.
    await expect(page.getByText("Use Acme as party 1.")).toBeVisible();
    await expect(page.getByText("Got it. Who is party 2?")).toBeVisible();
    // The fresh-chat welcome bubble is suppressed when history isn't empty.
    await expect(page.getByText(/draft a legal agreement/i)).toHaveCount(0);
  });
});
