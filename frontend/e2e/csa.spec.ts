import { expect, test } from "@playwright/test";

// End-to-end (mocked backend) coverage for the manifest-driven document
// pipeline, using the CSA as the pilot doc: structured cover page, body
// term-reference highlighting, manifest-driven edit form, and download
// gating on required fields.

const CSA_MANIFEST = {
  doc_id: "cloud-service-agreement",
  version: 1,
  sections: [
    { key: "parties", label: { zh: "当事方", en: "Parties" } },
    { key: "keyterms", label: { zh: "关键条款", en: "Key Terms" } },
  ],
  fields: [
    {
      key: "Provider",
      section: "parties",
      type: "string",
      required: true,
      label: { zh: "服务商", en: "Provider (company)" },
      example: "Globex Cloud, Inc.",
      aliases: ["Provider’s"],
    },
    {
      key: "Customer",
      section: "parties",
      type: "string",
      required: true,
      label: { zh: "客户", en: "Customer (company)" },
      example: "Acme, Inc.",
      aliases: ["Customer’s"],
    },
    {
      key: "Governing Law",
      section: "keyterms",
      type: "string",
      required: true,
      label: { zh: "适用法律", en: "Governing Law" },
    },
  ],
};

const CSA_TEMPLATE = {
  doc_id: "cloud-service-agreement",
  title: "Cloud Service Agreement (CSA)",
  standard_terms:
    "# Cloud Service Agreement\n\n" +
    '<span class="coverpage_link">Provider</span> grants ' +
    '<span class="coverpage_link">Customer</span> access under the ' +
    '<span class="keyterms_link">Governing Law</span>.',
  cover_page: null,
  manifest: CSA_MANIFEST,
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
  const stubDoc = {
    id: 1,
    doc_id: "cloud-service-agreement",
    title: "CSA draft",
    state: {},
    created_at: "2026-07-01T00:00:00",
    updated_at: "2026-07-01T00:00:00",
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
  await page.route("**/api/templates/cloud-service-agreement", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(CSA_TEMPLATE),
    }),
  );
});

/** Drive one chat turn that switches the app to the CSA and returns the
 * given field updates. */
async function switchToCsaViaChat(
  page: import("@playwright/test").Page,
  fieldUpdates: Record<string, string>,
) {
  await page.route("**/api/chat", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        assistant_message: "Noted. What else?",
        selected_doc_id: "cloud-service-agreement",
        mnda_updates: {},
        field_updates: fieldUpdates,
        done: false,
      }),
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "English" }).click();
  await page.getByLabel(/type a message/i).fill("I need a CSA");
  await page.getByRole("button", { name: /^send$/i }).click();
  await expect(page.getByText("Noted. What else?")).toBeVisible();
}

test.describe("CSA manifest pipeline", () => {
  test("chat switch renders the structured cover page and highlights body refs", async ({
    page,
  }) => {
    await switchToCsaViaChat(page, { Customer: "Acme, Inc." });

    // Structured cover page with manifest sections and the filled value.
    await expect(page.getByRole("heading", { name: "Cover Page" })).toBeVisible();
    await expect(page.getByText("Acme, Inc.", { exact: true })).toBeVisible();
    // Required-but-missing fields are flagged (Provider + Governing Law).
    await expect(page.getByText("[Not provided]")).toHaveCount(2);

    // Body term references: Customer defined (tooltip carries the value),
    // Governing Law still missing.
    const defined = page.locator(".term-defined", { hasText: "Customer" });
    await expect(defined).toHaveAttribute("title", "Customer: Acme, Inc.");
    await expect(
      page.locator(".term-missing", { hasText: "Governing Law" }),
    ).toBeVisible();
  });

  test("download unlocks only when all required cover-page fields are set", async ({
    page,
  }) => {
    await switchToCsaViaChat(page, { Customer: "Acme, Inc." });

    const download = page.getByRole("button", { name: /download pdf/i });
    await expect(download).toBeDisabled();

    // Fill the remaining required fields via the manifest-driven form tab.
    await page.getByRole("tab", { name: /edit fields/i }).click();
    await page.getByLabel(/Provider \(company\)/).fill("Globex Cloud, Inc.");
    await page.getByLabel(/Governing Law/).fill("Delaware");

    await expect(download).toBeEnabled();

    // And the cover page now shows every value with no missing markers.
    await expect(page.getByText("[Not provided]")).toHaveCount(0);
    await expect(page.getByText("Delaware", { exact: true })).toBeVisible();
  });
});
