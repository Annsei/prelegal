import { expect, test, type Page } from "@playwright/test";

type ManifestDoc = {
  docId:
    | "professional-services-agreement"
    | "data-processing-agreement"
    | "service-level-agreement"
    | "software-license-agreement"
    | "pilot-agreement"
    | "design-partner-agreement"
    | "partnership-agreement"
    | "business-associate-agreement"
    | "ai-addendum";
  title: string;
  firstField: { key: string; label: string; value: string };
  secondField: { key: string; label: string; value: string };
};

const MANIFEST_DOCS: ManifestDoc[] = [
  {
    docId: "professional-services-agreement",
    title: "Professional Services Agreement",
    firstField: { key: "委托方名称", label: "Client name", value: "Acme Co." },
    secondField: {
      key: "受托方名称",
      label: "Service provider name",
      value: "Globex Consulting Co.",
    },
  },
  {
    docId: "data-processing-agreement",
    title: "Data Processing Agreement",
    firstField: {
      key: "委托方名称",
      label: "Data principal name",
      value: "Acme Data Co.",
    },
    secondField: {
      key: "受托方名称",
      label: "Data processor name",
      value: "Globex Processing Co.",
    },
  },
  {
    docId: "service-level-agreement",
    title: "Service Level Agreement",
    firstField: { key: "服务方", label: "Service provider", value: "Globex Cloud Co." },
    secondField: { key: "可用率目标", label: "Availability target", value: "99.9%" },
  },
  {
    docId: "software-license-agreement",
    title: "Software License Agreement",
    firstField: { key: "许可方", label: "Licensor", value: "Globex Software Co." },
    secondField: { key: "许可费", label: "License fee", value: "人民币 120,000 元" },
  },
  {
    docId: "pilot-agreement",
    title: "Pilot Agreement",
    firstField: { key: "服务方", label: "Service provider", value: "Globex Pilot Co." },
    secondField: { key: "试点期限", label: "Pilot period", value: "2026-08-01 至 2026-10-31" },
  },
  {
    docId: "design-partner-agreement",
    title: "Design Partner Agreement",
    firstField: { key: "甲方", label: "Product provider", value: "Globex Product Co." },
    secondField: { key: "产品", label: "Product", value: "Customer insight platform" },
  },
  {
    docId: "partnership-agreement",
    title: "Channel Partnership Agreement",
    firstField: { key: "供应商", label: "Supplier", value: "Globex Software Co." },
    secondField: { key: "合作模式", label: "Partnership model", value: "转介绍" },
  },
  {
    docId: "business-associate-agreement",
    title: "Healthcare Data Cooperation Agreement",
    firstField: { key: "医疗机构", label: "Healthcare institution", value: "Example Hospital" },
    secondField: { key: "处理目的", label: "Processing purpose", value: "Patient portal support" },
  },
  {
    docId: "ai-addendum",
    title: "AI Services Addendum",
    firstField: { key: "客户", label: "Customer", value: "Acme Technology Co." },
    secondField: { key: "主协议", label: "Main agreement", value: "Cloud Services Agreement dated 2026-08-01" },
  },
];

type MockField = {
  key: string;
  status: "missing" | "pending_confirmation" | "confirmed";
  value: string | null;
  revision: number;
  provenance: unknown[];
  confirmed_at: string | null;
  confirmed_by_user_id: number | null;
  conflict: null;
};

async function installManifestTemplateBackend(page: Page, doc: ManifestDoc) {
  const manifest = {
    doc_id: doc.docId,
    version: 1,
    sections: [{ key: "parties", label: { zh: "当事人", en: "Parties" } }],
    fields: [
      {
        ...doc.firstField,
        section: "parties",
        type: "string",
        required: true,
        label: { zh: doc.firstField.key, en: doc.firstField.label },
      },
      {
        ...doc.secondField,
        section: "parties",
        type: "string",
        required: true,
        label: { zh: doc.secondField.key, en: doc.secondField.label },
      },
    ],
  };
  const fields: Record<string, MockField> = Object.fromEntries(
    manifest.fields.map((field) => [
      field.key,
      {
        key: field.key,
        status: "missing",
        value: null,
        revision: 0,
        provenance: [],
        confirmed_at: null,
        confirmed_by_user_id: null,
        conflict: null,
      },
    ]),
  );
  let revision = 0;
  const snapshot = () => ({
    schema_version: "draft-state.v1",
    manifest_version: 1,
    doc_id: doc.docId,
    revision,
    fields,
    validation_errors: [],
    applied_patches: {},
  });
  const record = () => ({
    id: 1,
    doc_id: doc.docId,
    title: doc.title,
    state: { draft_state: snapshot() },
    created_at: "2026-08-01T00:00:00",
    updated_at: "2026-08-01T00:00:00",
  });

  await page.route("**/api/documents", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ status: 200, body: "[]" });
      return;
    }
    await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(record()) });
  });
  await page.route(/\/api\/documents\/\d+$/, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(record()) }),
  );
  await page.route(`**/api/templates/${doc.docId}`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        doc_id: doc.docId,
        title: doc.title,
        cover_page: '<span class="coverpage_link">委托方名称</span>',
        standard_terms: '<span class="coverpage_link">受托方名称</span>',
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
  await page.route("**/api/chat", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        assistant_message: "Noted. What else should we confirm?",
        selected_doc_id: doc.docId,
        mnda_updates: {},
        field_updates: {
          [doc.firstField.key]: doc.firstField.value,
          [doc.secondField.key]: doc.secondField.value,
        },
        done: false,
      }),
    }),
  );
  await page.route(/\/api\/documents\/\d+\/field-patches$/, async (route) => {
    const body = (await route.request().postDataJSON()) as {
      operations: Array<{ op: "propose" | "confirm"; key: string; value?: string }>;
    };
    revision += 1;
    for (const operation of body.operations) {
      const field = fields[operation.key];
      field.status = operation.op === "confirm" ? "confirmed" : "pending_confirmation";
      field.value = operation.value ?? field.value;
      field.revision = revision;
      field.confirmed_at = operation.op === "confirm" ? "2026-08-01T00:00:00" : null;
      field.confirmed_by_user_id = operation.op === "confirm" ? 1 : null;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ snapshot: snapshot(), duplicate: false }),
    });
  });
  await page.route(/\/api\/documents\/\d+\/download-readiness$/, (route) => {
    const unresolved = Object.values(fields)
      .filter((field) => field.status !== "confirmed")
      .map((field) => field.key);
    route.fulfill({
      status: unresolved.length ? 409 : 200,
      contentType: "application/json",
      body: JSON.stringify(unresolved.length ? { detail: { unresolved_required_fields: unresolved } } : { ready: true }),
    });
  });
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem(
      "prelegal:session",
      JSON.stringify({
        user: { id: 1, email: "e2e@example.com", name: "", created_at: "2026-08-01T00:00:00" },
        token: "e2e-token",
      }),
    );
  });
});

for (const doc of MANIFEST_DOCS) {
  test(`${doc.docId} uses kernel proposals, confirmations, and download gating`, async ({ page }) => {
    await installManifestTemplateBackend(page, doc);
    await page.goto("/");
    await page.getByRole("button", { name: "English" }).click();
    await page.getByLabel(/type a message/i).fill(`Draft ${doc.title}`);
    await page.getByRole("button", { name: /^send$/i }).click();

    await expect(page.getByText("Pending confirmation").first()).toBeVisible();
    const download = page.getByRole("button", { name: /download docx/i });
    await expect(download).toBeDisabled();

    await page.getByRole("tab", { name: /edit fields/i }).click();
    const first = page
      .locator(`[id="docform-${doc.firstField.key}"]`)
      .locator("xpath=..");
    await first.getByRole("button", { name: "Confirm" }).click();
    const second = page
      .locator(`[id="docform-${doc.secondField.key}"]`)
      .locator("xpath=..");
    await second.getByRole("button", { name: "Confirm" }).click();

    await expect(download).toBeEnabled();
  });
}
