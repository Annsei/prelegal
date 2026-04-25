import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem(
      "prelegal:user",
      JSON.stringify({
        id: 1,
        email: "e2e@example.com",
        name: "",
        created_at: "2026-04-25T00:00:00",
      }),
    );
  });
});

test.describe("MNDA chat", () => {
  test("chat tab is the default editor and shows the welcome message", async ({
    page,
  }) => {
    await page.goto("/");
    // Welcome bubble (Chinese) is rendered into the chat panel.
    await expect(page.getByText(/起草一份双方保密协议/)).toBeVisible();
    // English welcome appears after switching language.
    await page.getByRole("button", { name: "English" }).click();
    await expect(page.getByText(/draft a Mutual NDA/i)).toBeVisible();
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
