import { expect, test } from "@playwright/test";

test.describe("Login flow", () => {
  test("unauthenticated visitors are redirected to /login", async ({
    page,
  }) => {
    await page.goto("/");
    await page.waitForURL(/\/login$/);
    await expect(page.getByRole("heading", { name: "Prelegal" })).toBeVisible();
  });

  test("submitting the login form lands the user on /", async ({ page }) => {
    // Stub the API call — the dev server doesn't have /api routes, and we
    // don't want the test to depend on a running backend.
    await page.route("**/api/auth/login", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: 42,
          email: "smoke@example.com",
          name: "",
          created_at: "2026-04-25T00:00:00",
        }),
      }),
    );

    await page.goto("/login");
    await page.getByLabel("Email").fill("smoke@example.com");
    await page.getByRole("button", { name: "Sign in" }).click();

    await page.waitForURL(/\/$/);
    await expect(page.getByText("smoke@example.com")).toBeVisible();
  });

  test("sign-out clears the session and bounces back to /login", async ({
    page,
  }) => {
    // Visit /login once so we have an origin against which to seed localStorage,
    // then plant the session and reload the homepage.
    await page.goto("/login");
    await page.evaluate(() => {
      window.localStorage.setItem(
        "prelegal:user",
        JSON.stringify({
          id: 1,
          email: "byebye@example.com",
          name: "",
          created_at: "2026-04-25T00:00:00",
        }),
      );
    });
    await page.goto("/");
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.waitForURL(/\/login$/);

    const stored = await page.evaluate(() =>
      window.localStorage.getItem("prelegal:user"),
    );
    expect(stored).toBeNull();
  });
});
