import { expect, type Page, test } from "@playwright/test";

const SESSION_KEY = "prelegal:session";

async function seedSession(page: Page, email = "byebye@example.com"): Promise<void> {
  await page.evaluate(
    ({ key, email }) => {
      window.localStorage.setItem(
        key,
        JSON.stringify({
          user: {
            id: 1,
            email,
            name: "",
            created_at: "2026-04-25T00:00:00",
          },
          token: "test-token",
        }),
      );
    },
    { key: SESSION_KEY, email },
  );
}

// The home page calls /api/documents on mount; with no real backend the
// dev server would 404 and our 401 fallback would kick in (clearing the
// session and bouncing to /login). Stub the list to an empty array so
// the home page renders normally.
async function stubEmptyDocumentsList(page: Page): Promise<void> {
  await page.route("**/api/documents", (route) => {
    if (route.request().method() === "GET") {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      });
    } else {
      route.continue();
    }
  });
}

test.describe("Login flow", () => {
  test("unauthenticated visitors are redirected to /login", async ({
    page,
  }) => {
    await page.goto("/");
    await page.waitForURL(/\/login$/);
    // Brand chip on the marketing column ("Prelegal") is the most stable
    // anchor — the H2 changes between login/register modes.
    await expect(page.getByText("Prelegal", { exact: true })).toBeVisible();
  });

  test("submitting the login form lands the user on /", async ({ page }) => {
    await page.route("**/api/auth/login", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          user: {
            id: 42,
            email: "smoke@example.com",
            name: "",
            created_at: "2026-04-25T00:00:00",
          },
          token: "smoke-token",
        }),
      }),
    );
    await stubEmptyDocumentsList(page);

    await page.goto("/login");
    await page.getByRole("button", { name: "English" }).click();
    await page.getByLabel(/email/i).fill("smoke@example.com");
    await page.getByLabel(/password/i).fill("secretpw1");
    await page.getByRole("button", { name: /sign in/i }).click();

    await page.waitForURL(/\/$/);
    await expect(page.getByText("smoke@example.com")).toBeVisible();
  });

  test("sign-out clears the session and bounces back to /login", async ({
    page,
  }) => {
    await stubEmptyDocumentsList(page);
    await page.route("**/api/auth/logout", (route) =>
      route.fulfill({ status: 204 }),
    );

    // Visit /login once so we have an origin against which to seed localStorage,
    // then plant the session and reload the homepage.
    await page.goto("/login");
    await seedSession(page);
    await page.goto("/");
    await page.getByRole("button", { name: /退出登录|Sign out/ }).click();
    await page.waitForURL(/\/login$/);

    const stored = await page.evaluate(
      (key) => window.localStorage.getItem(key),
      SESSION_KEY,
    );
    expect(stored).toBeNull();
  });
});
