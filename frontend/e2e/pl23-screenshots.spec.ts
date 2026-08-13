import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const CAPTURE = process.env.PL23_CAPTURE_SCREENSHOTS === "1";
const SCREENSHOT_DIR = path.resolve(process.cwd(), "../docs/screenshots");
const TEMPLATE_DIR = path.resolve(process.cwd(), "../templates");

const manifest = JSON.parse(
  readFileSync(
    path.join(TEMPLATE_DIR, "manifests/pilot-agreement.json"),
    "utf8",
  ),
) as {
  version: number;
  fields: Array<{ key: string }>;
};
const coverPage = readFileSync(
  path.join(TEMPLATE_DIR, "pilot-agreement/cover_page.md"),
  "utf8",
);
const standardTerms = readFileSync(
  path.join(TEMPLATE_DIR, "pilot-agreement/standard_terms.md"),
  "utf8",
);

function missingField(key: string) {
  return {
    key,
    status: "missing",
    value: null,
    revision: 0,
    provenance: [],
    confirmed_at: null,
    confirmed_by_user_id: null,
    conflict: null,
  };
}

function screenshotRecord() {
  const fields = Object.fromEntries(
    manifest.fields.map((field) => [field.key, missingField(field.key)]),
  );
  fields.服务方 = {
    ...missingField("服务方"),
    status: "confirmed",
    value: "北辰软件（上海）有限公司",
    revision: 1,
    confirmed_at: "2026-08-06T00:00:00+00:00",
    confirmed_by_user_id: 1,
  };
  fields.客户 = {
    ...missingField("客户"),
    status: "conflict",
    value: "海岳科技（北京）有限公司",
    revision: 4,
    confirmed_at: "2026-08-06T00:00:00+00:00",
    confirmed_by_user_id: 1,
    conflict: {
      base_value: "海岳科技（北京）有限公司",
      proposed_value: "海岳数据（北京）有限公司",
      provenance: {
        patch_id: "screenshot-conflict",
        source: "llm",
        operation: "propose",
        value: "海岳数据（北京）有限公司",
      },
    },
  };
  fields.试点期限 = {
    ...missingField("试点期限"),
    status: "pending_confirmation",
    value: "自生效日起 90 日",
    revision: 2,
  };
  fields.试点收费方式 = {
    ...missingField("试点收费方式"),
    status: "confirmed",
    value: "免费",
    revision: 3,
    confirmed_at: "2026-08-06T00:00:00+00:00",
    confirmed_by_user_id: 1,
  };
  return {
    id: 1,
    doc_id: "pilot-agreement",
    title: "客户洞察平台免费试点协议",
    state: {
      chat: [
        { role: "user", content: "我们准备为客户做一个 90 天的免费试点。" },
        {
          role: "assistant",
          content:
            "已记录免费试点。客户名称存在一个新候选值，请在编辑页确认采用哪一个。",
        },
      ],
      draft_state: {
        schema_version: "draft-state.v1",
        manifest_version: manifest.version,
        doc_id: "pilot-agreement",
        revision: 4,
        fields,
        validation_errors: [],
        applied_patches: {},
      },
    },
    created_at: "2026-08-06T00:00:00",
    updated_at: "2026-08-06T00:05:00",
  };
}

async function installScreenshotBackend(page: Page) {
  const record = screenshotRecord();
  await page.route("**/api/documents", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: record.id,
            doc_id: record.doc_id,
            title: record.title,
            created_at: record.created_at,
            updated_at: record.updated_at,
          },
        ]),
      });
      return;
    }
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify(record),
    });
  });
  await page.route("**/api/documents/1", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(record),
    }),
  );
  await page.route("**/api/templates/pilot-agreement", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        doc_id: "pilot-agreement",
        title: "试点协议",
        cover_page: coverPage,
        standard_terms: standardTerms,
        manifest,
      }),
    }),
  );
  await page.route("**/api/templates/mutual-nda", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        doc_id: "mutual-nda",
        title: "双方保密协议",
        cover_page: "",
        standard_terms: "# 双方保密协议",
        manifest: null,
      }),
    }),
  );
}

test("capture PL-23 visual evidence", async ({ page }) => {
  test.skip(!CAPTURE, "Run with PL23_CAPTURE_SCREENSHOTS=1 to refresh evidence.");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "登录" })).toBeVisible();
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, "pl23-login.png"),
  });

  await installScreenshotBackend(page);
  await page.evaluate(() => {
    window.localStorage.setItem(
      "prelegal:session",
      JSON.stringify({
        user: {
          id: 1,
          email: "reviewer@example.com",
          name: "审核用户",
          created_at: "2026-08-06T00:00:00",
        },
        token: "screenshot-token",
      }),
    );
    window.localStorage.setItem("prelegal:activeDocId", "1");
  });
  await page.goto("/");
  await expect(page.getByText("客户洞察平台免费试点协议")).toBeVisible();
  await expect(page.locator(".workspace-grid")).toBeVisible();
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, "pl23-workspace-three-column.png"),
  });

  await page.getByRole("button", { name: "PDF", exact: true }).click();
  await expect(page.getByRole("button", { name: /下载 PDF/ })).toBeVisible();
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, "pl23-export-controls.png"),
    clip: { x: 940, y: 0, width: 500, height: 180 },
  });
  await page.getByRole("button", { name: "DOCX", exact: true }).click();

  const firstChapter = page
    .locator('span.header_2[id="1"]')
    .locator("xpath=../..");
  await expect(firstChapter.locator(".term-defined").first()).toBeVisible();
  await expect(firstChapter.locator(".term-pending").first()).toBeVisible();
  await expect(firstChapter.locator(".term-missing").first()).toBeVisible();
  await firstChapter.screenshot({
    path: path.join(SCREENSHOT_DIR, "pl23-preview-term-states.png"),
  });

  await page.getByRole("button", { name: "English" }).click();
  await page.getByRole("tab", { name: /edit fields/i }).click();
  await expect(page.locator('[data-field-status="conflict"]')).toBeVisible();
  await expect(
    page.locator('[data-field-status="confirmed"]').first(),
  ).toBeVisible();
  await expect(
    page.locator('[data-field-status="pending_confirmation"]'),
  ).toBeVisible();
  await expect(page.locator('[data-field-status="missing"]').first()).toBeVisible();
  await page.locator(".form-panel").screenshot({
    path: path.join(SCREENSHOT_DIR, "pl23-docform-states-en.png"),
  });
  expect(await page.evaluate(() => document.body.scrollWidth)).toBeLessThanOrEqual(
    1440,
  );

  const feesChapter = page
    .locator('span.header_2[id="3"]')
    .locator("xpath=../..");
  await expect(feesChapter).toContainText("约定为免费的");
  await expect(feesChapter).not.toContainText("逾期付款");
  await expect(feesChapter).not.toContainText("退费");
  await feesChapter.screenshot({
    path: path.join(SCREENSHOT_DIR, "pl23-pilot-free-terms-hidden.png"),
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, "pl23-workspace-mobile.png"),
  });
  expect(await page.evaluate(() => document.body.scrollWidth)).toBeLessThanOrEqual(
    390,
  );

  await page.goto("/login");
  await page.getByRole("button", { name: "English" }).click();
  expect(await page.evaluate(() => document.body.scrollWidth)).toBeLessThanOrEqual(
    390,
  );
});

test("export format and download controls never overlap", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await installScreenshotBackend(page);
  await page.goto("/login");
  await page.evaluate(() => {
    window.localStorage.setItem(
      "prelegal:session",
      JSON.stringify({
        user: {
          id: 1,
          email: "reviewer@example.com",
          name: "审核用户",
          created_at: "2026-08-06T00:00:00",
        },
        token: "screenshot-token",
      }),
    );
    window.localStorage.setItem("prelegal:activeDocId", "1");
  });
  await page.goto("/");
  await expect(page.locator(".workspace-grid")).toBeVisible();

  const formatGroup = page.getByRole("group", { name: "下载格式" });
  const downloadButton = page.getByRole("button", { name: /下载 DOCX/ });
  await expect(formatGroup).toBeVisible();
  await expect(page.getByRole("button", { name: "DOCX", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  for (const width of [1440, 820, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    const formatBox = await formatGroup.boundingBox();
    const downloadBox = await downloadButton.boundingBox();
    expect(formatBox).not.toBeNull();
    expect(downloadBox).not.toBeNull();
    if (!formatBox || !downloadBox) continue;

    const separatedHorizontally =
      formatBox.x + formatBox.width <= downloadBox.x ||
      downloadBox.x + downloadBox.width <= formatBox.x;
    const separatedVertically =
      formatBox.y + formatBox.height <= downloadBox.y ||
      downloadBox.y + downloadBox.height <= formatBox.y;
    expect(separatedHorizontally || separatedVertically).toBe(true);
    expect(await page.evaluate(() => document.body.scrollWidth)).toBeLessThanOrEqual(
      width,
    );
  }
});
