import { expect, test, type Page } from "@playwright/test";

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
      aliases: ["Provider's"],
    },
    {
      key: "Customer",
      section: "parties",
      type: "string",
      required: true,
      label: { zh: "客户", en: "Customer (company)" },
      example: "Acme, Inc.",
      aliases: ["Customer's"],
    },
    {
      key: "Governing Law",
      section: "keyterms",
      type: "string",
      required: true,
      label: { zh: "适用法律", en: "Governing Law" },
    },
    {
      key: "Auto Renew",
      section: "keyterms",
      type: "string",
      required: false,
      label: { zh: "自动续期", en: "Auto-renewal" },
    },
    {
      key: "Non-Renewal Notice Period",
      section: "keyterms",
      type: "string",
      required: false,
      required_when: {
        field: "Auto Renew",
        op: "equals",
        value: "Yes",
      },
      label: { zh: "不续约通知期", en: "Non-renewal Notice Period" },
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

const MNDA_TEMPLATE = {
  doc_id: "mutual-nda",
  title: "双方保密协议",
  cover_page: "# 双方保密协议 · 封面页\n\n| 条款 | 约定内容 |\n| --- | --- |",
  standard_terms: "# 双方保密协议 · 标准条款\n\n双方按封面页约定处理保密信息。",
  manifest: {
    doc_id: "mutual-nda",
    version: 1,
    sections: [],
    fields: [],
  },
};

type FieldStatus =
  | "confirmed"
  | "pending_confirmation"
  | "conflict"
  | "missing";

type MockField = {
  key: string;
  status: FieldStatus;
  value?: string | null;
  revision: number;
  provenance: unknown[];
  confirmed_at?: string | null;
  confirmed_by_user_id?: number | null;
  conflict?: { base_value?: string | null; proposed_value: string } | null;
};

type MockSnapshot = {
  schema_version: "draft-state.v1";
  manifest_version: number;
  doc_id: string;
  revision: number;
  fields: Record<string, MockField>;
  validation_errors: unknown[];
  applied_patches: Record<string, unknown>;
};

type MockPatchOperation = {
  op: "propose" | "confirm" | "reject";
  key: string;
  value?: string;
};

type MockPatchBody = {
  patch_id: string;
  base_revision: number;
  source: string;
  operations: MockPatchOperation[];
};

type MockDocState = {
  chat?: unknown;
  fields?: Record<string, string>;
  draft_state?: MockSnapshot | null;
};

type MockPutBody = {
  title?: string;
  state?: {
    chat?: unknown;
    fields?: Record<string, string>;
  };
};

function emptySnapshot(revision = 0): MockSnapshot {
  return {
    schema_version: "draft-state.v1",
    manifest_version: 1,
    doc_id: "cloud-service-agreement",
    revision,
    fields: Object.fromEntries(
      CSA_MANIFEST.fields.map((field) => [
        field.key,
        {
          key: field.key,
          status: "missing" as const,
          value: null,
          revision: 0,
          provenance: [],
          confirmed_at: null,
          confirmed_by_user_id: null,
          conflict: null,
        },
      ]),
    ),
    validation_errors: [],
    applied_patches: {},
  };
}

function legacySnapshot(): MockSnapshot {
  const snapshot = emptySnapshot();
  snapshot.fields.Customer = {
    key: "Customer",
    status: "pending_confirmation",
    value: "Legacy Co",
    revision: 0,
    provenance: [
      {
        patch_id: "legacy-migration",
        source: "system",
        operation: "legacy_unverified",
        value: "Legacy Co",
        at: null,
      },
    ],
    confirmed_at: null,
    confirmed_by_user_id: null,
    conflict: null,
  };
  return snapshot;
}

function confirmedValues(snapshot: MockSnapshot): Record<string, string> {
  const values: Record<string, string> = {};
  for (const [key, field] of Object.entries(snapshot.fields)) {
    if (field.status === "confirmed" && field.value) values[key] = field.value;
  }
  return values;
}

function stableValues(snapshot: MockSnapshot | null): Record<string, string> {
  const values: Record<string, string> = {};
  if (!snapshot) return values;
  for (const [key, field] of Object.entries(snapshot.fields)) {
    if (field.status === "confirmed" && field.value) values[key] = field.value;
    if (field.status === "conflict" && field.confirmed_at && field.value) {
      values[key] = field.value;
    }
  }
  return values;
}

function requiredWhenMatches(
  condition: unknown,
  values: Record<string, string>,
): boolean {
  if (!condition || typeof condition !== "object") return false;
  const raw = condition as {
    field?: unknown;
    op?: unknown;
    value?: unknown;
    values?: unknown;
  };
  if (typeof raw.field !== "string") return false;
  const value = values[raw.field];
  const op = typeof raw.op === "string" ? raw.op : "equals";
  if (op === "equals") return value === raw.value;
  if (op === "not_equals") return Boolean(value) && value !== raw.value;
  if (op === "in") return Array.isArray(raw.values) && raw.values.includes(value);
  if (op === "exists") return Boolean(value);
  return false;
}

function applyMockPatch(snapshot: MockSnapshot, body: MockPatchBody): MockSnapshot {
  const next = structuredClone(snapshot) as MockSnapshot;
  const activeOps = body.operations.filter((op) => {
    const field = next.fields[op.key];
    if (!field || op.op !== "propose") return true;
    const candidate = field.conflict?.proposed_value ?? field.value;
    return candidate !== op.value;
  });
  if (activeOps.length === 0) return next;
  next.revision += 1;
  for (const op of activeOps) {
    const field = next.fields[op.key];
    if (op.op === "propose") {
      if (field.status === "confirmed" && field.value && field.value !== op.value) {
        field.status = "conflict";
        field.conflict = { base_value: field.value, proposed_value: op.value };
      } else {
        field.status = "pending_confirmation";
        field.value = op.value;
        field.conflict = null;
        field.confirmed_at = null;
        field.confirmed_by_user_id = null;
      }
    } else if (op.op === "confirm") {
      field.status = "confirmed";
      field.value = op.value ?? field.conflict?.proposed_value ?? field.value;
      field.conflict = null;
      field.confirmed_at = "2026-07-31T00:00:00+00:00";
      field.confirmed_by_user_id = 1;
    } else if (op.op === "reject") {
      if (field.conflict?.base_value) {
        field.status = "confirmed";
        field.value = field.conflict.base_value;
      } else {
        field.status = "missing";
        field.value = null;
      }
      field.conflict = null;
    }
    field.revision = next.revision;
    field.provenance.push({
      patch_id: body.patch_id,
      source: body.source,
      operation: op.op,
      value: op.value ?? null,
    });
  }
  return next;
}

async function installMockBackend(
  page: Page,
  options: { legacy?: boolean; downloadBlockOnce?: string[] } = {},
) {
  const events: { patches: MockPatchBody[]; puts: MockPutBody[] } = {
    patches: [],
    puts: [],
  };
  let downloadBlockOnce = options.downloadBlockOnce
    ? [...options.downloadBlockOnce]
    : null;
  let snapshot: MockSnapshot | null = options.legacy ? legacySnapshot() : null;
  let doc = {
    id: 1,
    doc_id: "cloud-service-agreement",
    title: "CSA draft",
    state: (options.legacy
      ? {
          fields: { Customer: "Legacy Co" },
          draft_state: snapshot,
        }
      : {}) as MockDocState,
    created_at: "2026-07-01T00:00:00",
    updated_at: "2026-07-01T00:00:00",
  };

  function syncState() {
    if (!snapshot) return;
    doc = {
      ...doc,
      state: {
        ...doc.state,
        draft_state: snapshot,
        fields: {
          ...(doc.state.fields ?? {}),
          ...confirmedValues(snapshot),
        },
      },
    };
  }

  await page.route("**/api/documents", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      });
      return;
    }
    if (route.request().method() === "POST") {
      const body = (await route.request().postDataJSON()) as {
        doc_id: string;
        title: string;
        state?: MockDocState;
      };
      doc = {
        ...doc,
        doc_id: body.doc_id,
        title: body.title,
        state: body.state ?? {},
      };
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(doc),
      });
      return;
    }
    await route.continue();
  });

  await page.route(/\/api\/documents\/1\/field-patches$/, async (route) => {
    const body = (await route.request().postDataJSON()) as MockPatchBody;
    events.patches.push(body);
    if (body.source === "system") {
      await route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({
          detail: {
            validation_errors: [{ kind: "forbidden_source" }],
          },
        }),
      });
      return;
    }
    snapshot = applyMockPatch(snapshot ?? emptySnapshot(), body);
    syncState();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ snapshot, duplicate: false }),
    });
  });

  await page.route(
    /\/api\/documents\/1\/download\?format=(docx|pdf)$/,
    async (route) => {
      if (downloadBlockOnce) {
        const unresolved = downloadBlockOnce;
        downloadBlockOnce = null;
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({
            detail: {
              validation_errors: [{ kind: "download_blocked" }],
              unresolved_required_fields: unresolved,
            },
          }),
        });
        return;
      }
      const stable = stableValues(snapshot);
      const unresolved = CSA_MANIFEST.fields
        .filter(
          (field) =>
            field.required || requiredWhenMatches(field.required_when, stable),
        )
        .filter((field) => snapshot?.fields[field.key]?.status !== "confirmed")
        .map((field) => field.key);
      if (unresolved.length > 0) {
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({
            detail: {
              validation_errors: [{ kind: "download_blocked" }],
              unresolved_required_fields: unresolved,
            },
          }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType:
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers: {
          "Content-Disposition":
            "attachment; filename=agreement.docx; filename*=UTF-8''CSA-20260803.docx",
        },
        body: "PK-mocked-docx",
      });
    },
  );

  await page.route(/\/api\/documents\/1$/, async (route) => {
    if (route.request().method() === "PUT") {
      const body = (await route.request().postDataJSON()) as MockPutBody;
      events.puts.push(body);
      doc = { ...doc, title: body.title ?? doc.title };
      if (body.state) {
        doc = {
          ...doc,
          state: {
            ...doc.state,
            chat: body.state.chat ?? doc.state.chat,
          },
        };
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(doc),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(doc),
    });
  });

  await page.route("**/api/templates/cloud-service-agreement", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(CSA_TEMPLATE),
    }),
  );
  await page.route("**/api/templates/mutual-nda", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MNDA_TEMPLATE),
    }),
  );

  return events;
}

async function mockChat(
  page: Page,
  fieldUpdates: Record<string, string>,
  assistant = "Noted. What else?",
) {
  await page.route("**/api/chat", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        assistant_message: assistant,
        selected_doc_id: "cloud-service-agreement",
        mnda_updates: {},
        field_updates: fieldUpdates,
        done: false,
      }),
    }),
  );
}

async function switchToCsaViaChat(
  page: Page,
  fieldUpdates: Record<string, string>,
) {
  await mockChat(page, fieldUpdates);
  await page.goto("/");
  await page.getByRole("button", { name: "English" }).click();
  await page.getByLabel(/type a message/i).fill("I need a CSA");
  await page.getByRole("button", { name: /^send$/i }).click();
  await expect(page.getByText("Noted. What else?")).toBeVisible();
}

async function fillAndConfirmField(
  page: Page,
  label: RegExp,
  value: string,
) {
  const input = page.getByLabel(label);
  const field = input.locator("xpath=ancestor::div[1]");
  await input.fill(value);
  const confirm = field.getByRole("button", { name: "Confirm" });
  await expect(confirm).toBeEnabled();
  await confirm.click();
  await expect(field.getByText("Confirmed", { exact: true })).toBeVisible();
}

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
});

test.describe("CSA document-state kernel adoption", () => {
  test("chat field updates are submitted as LLM proposals and render pending", async ({
    page,
  }) => {
    const events = await installMockBackend(page);
    await switchToCsaViaChat(page, { Customer: "Acme, Inc." });

    expect(events.patches[0]).toMatchObject({
      source: "llm",
      base_revision: 0,
      operations: [{ op: "propose", key: "Customer", value: "Acme, Inc." }],
    });
    await expect(page.getByText("Acme, Inc.")).toBeVisible();
    await expect(page.getByText("Pending confirmation")).toBeVisible();
    await expect(
      page.getByRole("button", { name: /download docx/i }),
    ).toBeDisabled();

    await expect
      .poll(() => events.puts.length)
      .toBeGreaterThanOrEqual(1);
    expect(events.puts.at(-1).state.fields).toBeUndefined();
  });

  test("form confirmation writes through field-patches", async ({ page }) => {
    const events = await installMockBackend(page);
    await switchToCsaViaChat(page, { Customer: "Acme, Inc." });

    await page.getByRole("tab", { name: /edit fields/i }).click();
    await page.getByRole("button", { name: "Confirm" }).nth(1).click();

    await expect(page.getByText("Confirmed").first()).toBeVisible();
    expect(events.patches[1]).toMatchObject({
      source: "form",
      base_revision: 1,
      operations: [{ op: "confirm", key: "Customer", value: "Acme, Inc." }],
    });
  });

  test("conflicts show base and candidate and can be resolved both ways", async ({
    page,
  }) => {
    const events = await installMockBackend(page);
    await switchToCsaViaChat(page, { Customer: "Acme, Inc." });
    await page.getByRole("tab", { name: /edit fields/i }).click();
    await page.getByLabel(/Customer \(company\)/).fill("Acme, Inc.");
    await page.getByRole("button", { name: "Confirm" }).nth(1).click();

    await mockChat(page, { Customer: "Beta LLC" }, "Candidate noted.");
    await page.getByRole("tab", { name: /ai chat/i }).click();
    await page.getByLabel(/type a message/i).fill("Actually use Beta.");
    await page.getByRole("button", { name: /^send$/i }).click();

    await expect(page.getByText("Conflict")).toBeVisible();
    await expect(page.getByText("Current: Acme, Inc.")).toBeVisible();
    await expect(page.getByText("Candidate: Beta LLC")).toBeVisible();
    await page.getByRole("tab", { name: /edit fields/i }).click();
    await page.getByRole("button", { name: "Reject" }).first().click();
    await expect(page.getByText("Conflict")).toHaveCount(0);
    await expect(page.getByText("Acme, Inc.")).toBeVisible();

    await mockChat(page, { Customer: "Beta LLC" }, "Candidate noted again.");
    await page.getByRole("tab", { name: /ai chat/i }).click();
    await page.getByLabel(/type a message/i).fill("Try Beta again.");
    await page.getByRole("button", { name: /^send$/i }).click();
    await page.getByRole("tab", { name: /edit fields/i }).click();
    await page.getByRole("button", { name: "Confirm" }).nth(1).click();
    await expect(
      page.getByLabel("Cover Page").getByText("Beta LLC").first(),
    ).toBeVisible();

    expect(events.patches.some((patch) => patch.operations[0].op === "reject"))
      .toBe(true);
    expect(events.patches.at(-1)).toMatchObject({
      source: "form",
      operations: [{ op: "confirm", key: "Customer", value: "Beta LLC" }],
    });
  });

  test("download gate unlocks only after all required fields are confirmed", async ({
    page,
  }) => {
    await installMockBackend(page);
    await switchToCsaViaChat(page, { Customer: "Acme, Inc." });
    const download = page.getByRole("button", { name: /download docx/i });
    await expect(download).toBeDisabled();

    await page.getByRole("tab", { name: /edit fields/i }).click();
    await fillAndConfirmField(
      page,
      /Provider \(company\)/,
      "Globex Cloud, Inc.",
    );
    await fillAndConfirmField(page, /Customer \(company\)/, "Acme, Inc.");
    await fillAndConfirmField(page, /Governing Law/, "PRC law");

    await expect(download).toBeEnabled();
  });

  test("download 409 lists unresolved fields by manifest label", async ({
    page,
  }) => {
    await installMockBackend(page, {
      downloadBlockOnce: ["Non-Renewal Notice Period"],
    });
    await switchToCsaViaChat(page, { Customer: "Acme, Inc." });

    await page.getByRole("tab", { name: /edit fields/i }).click();
    await fillAndConfirmField(
      page,
      /Provider \(company\)/,
      "Globex Cloud, Inc.",
    );
    await fillAndConfirmField(page, /Customer \(company\)/, "Acme, Inc.");
    await fillAndConfirmField(page, /Governing Law/, "PRC law");

    const download = page.getByRole("button", { name: /download docx/i });
    await expect(download).toBeEnabled();
    await download.click();

    const alert = page
      .locator('[role="alert"]')
      .filter({
        hasText: "Confirm these required fields before downloading:",
      });
    await expect(alert).toContainText(
      "Confirm these required fields before downloading:",
    );
    await expect(alert).toContainText("Non-renewal Notice Period");

    await page.getByLabel(/Non-renewal Notice Period/).fill("30 days");
    await page.getByRole("button", { name: "Confirm" }).nth(4).click();
    const downloadEvent = page.waitForEvent("download");
    await download.click();
    const savedFile = await downloadEvent;
    expect(savedFile.suggestedFilename()).toBe("CSA-20260803.docx");
    await expect(alert).toHaveCount(0);
  });

  test("legacy CSA drafts restored from GET render as pending until confirmed", async ({
    page,
  }) => {
    await page.addInitScript(() => {
      window.localStorage.setItem("prelegal:activeDocId", "1");
    });
    await installMockBackend(page, { legacy: true });

    await page.goto("/");
    await page.getByRole("button", { name: "English" }).click();

    await expect(page.getByText("Legacy Co")).toBeVisible();
    await expect(page.getByText("Pending confirmation")).toBeVisible();
    await page.getByRole("tab", { name: /edit fields/i }).click();
    await page.getByRole("button", { name: "Confirm" }).nth(1).click();
    await expect(page.getByText("Confirmed").first()).toBeVisible();
  });
});
