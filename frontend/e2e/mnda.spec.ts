import { type Page, expect, test } from "@playwright/test";

// Most form fields carry an id — prefer id selectors over getByLabel so help-text
// spans nested inside <label> don't confuse accessible-name matching.

// `/` now requires a session, otherwise it redirects to /login. Plant a
// fake session and stub the documents API so each test lands directly on
// the MNDA app.
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

// Chat is the default editor; tests that interact with form inputs need to
// click into the manual-edit tab first.
async function openFormTab(page: Page): Promise<void> {
  await page.getByRole("tab", { name: /手动编辑|Edit fields/ }).click();
}

test.describe("Mutual NDA generator", () => {
  test("renders the app with form and preview visible", async ({ page }) => {
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "法律协议生成器" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", {
        name: "Mutual Non-Disclosure Agreement",
        level: 1,
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Standard Terms", level: 2 }),
    ).toBeVisible();
  });

  test("form input flows through to the live preview", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "English" }).click();
    await openFormTab(page);

    await page.locator("#purpose").fill("Exploring a strategic partnership.");
    await page.locator("#governingLaw").fill("California");
    await page
      .locator("#jurisdiction")
      .fill("courts located in San Francisco, CA");
    await page.locator("#party1-company").fill("Acme, Inc.");
    await page.locator("#party1-signerName").fill("Jane Doe");
    await page.locator("#party2-company").fill("Globex Corp.");

    const doc = page.locator("[data-print-root]");
    await expect(doc).toContainText("Exploring a strategic partnership.");
    await expect(doc).toContainText("California");
    await expect(doc).toContainText("courts located in San Francisco, CA");
    await expect(doc).toContainText("Acme, Inc.");
    await expect(doc).toContainText("Jane Doe");
    await expect(doc).toContainText("Globex Corp.");
  });

  test("MNDA term mode toggles propagate to Section 5 body", async ({
    page,
  }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "English" }).click();
    await openFormTab(page);

    const doc = page.locator("[data-print-root]");
    await expect(doc).toContainText("1 year(s) from the Effective Date");

    // Select the second MNDA-term radio (continues).
    await page.locator('input[name="mndaTermMode"]').nth(1).check();
    await expect(doc).toContainText("term until terminated");

    // Select the second confidentiality radio (perpetual).
    await page.locator('input[name="confidentialityMode"]').nth(1).check();
    await expect(doc).toContainText("in perpetuity");
  });

  test("editing the year number auto-selects the expires radio", async ({
    page,
  }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "English" }).click();
    await openFormTab(page);

    // Switch MNDA term to "continues".
    await page.locator('input[name="mndaTermMode"]').nth(1).check();
    await expect(
      page.locator('input[name="mndaTermMode"]').nth(1),
    ).toBeChecked();

    // Edit the first year number input — should flip the radio.
    await page.getByRole("spinbutton").first().fill("3");

    await expect(
      page.locator('input[name="mndaTermMode"]').first(),
    ).toBeChecked();
    await expect(page.locator("[data-print-root]")).toContainText(
      "3 year(s) from the Effective Date",
    );
  });

  test("language toggle swaps UI labels but keeps legal text in English", async ({
    page,
  }) => {
    await page.goto("/");
    await openFormTab(page);

    // Default locale is zh. The Purpose label text starts with "目的".
    await expect(page.locator('label[for="purpose"]')).toContainText("目的");

    // Legal doc stays English.
    await expect(
      page.getByRole("heading", {
        name: "Mutual Non-Disclosure Agreement",
        level: 1,
      }),
    ).toBeVisible();

    // Switch to English.
    await page.getByRole("button", { name: "English" }).click();
    await expect(page.locator('label[for="purpose"]')).toContainText("Purpose");

    // Toggle back.
    await page.getByRole("button", { name: "中文" }).click();
    await expect(page.locator('label[for="purpose"]')).toContainText("目的");
  });

  test("triggers window.print() when Download PDF is clicked", async ({
    page,
  }) => {
    await page.goto("/");
    await page.evaluate(() => {
      (window as unknown as { __printed: boolean }).__printed = false;
      window.print = () => {
        (window as unknown as { __printed: boolean }).__printed = true;
      };
    });

    await page.getByRole("button", { name: /下载 PDF|Download PDF/ }).click();

    const called = await page.evaluate(
      () => (window as unknown as { __printed: boolean }).__printed,
    );
    expect(called).toBe(true);
  });

  test("print stylesheet hides the form and keeps only the document", async ({
    page,
  }) => {
    await page.goto("/");
    await openFormTab(page);
    await page.emulateMedia({ media: "print" });

    const formContainer = page
      .locator(".no-print")
      .filter({ has: page.locator("form") });
    // Guard: ensure the locator resolved — otherwise toBeHidden() would pass
    // vacuously if the class name or structure ever changed.
    await expect(formContainer).toHaveCount(1);
    await expect(formContainer).toBeHidden();

    await expect(page.locator("[data-print-root]")).toBeVisible();
  });
});
