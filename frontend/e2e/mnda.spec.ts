import { type Page, expect, test } from "@playwright/test";

const MNDA_MANIFEST = {
  doc_id: "mutual-nda",
  version: 1,
  sections: [
    { key: "keyterms", label: { zh: "关键条款", en: "Key Terms" } },
    { key: "parties", label: { zh: "签署方", en: "Parties" } },
    { key: "changes", label: { zh: "标准条款修订", en: "Standard-Term Changes" } },
  ],
  fields: [
    {
      key: "保密用途",
      section: "keyterms",
      type: "text",
      required: true,
      label: { zh: "保密用途", en: "Confidential Purpose" },
      example: "评估融资合作",
    },
    {
      key: "生效日期",
      section: "keyterms",
      type: "date",
      required: true,
      label: { zh: "生效日期", en: "Effective Date" },
    },
    {
      key: "协议期限",
      section: "keyterms",
      type: "string",
      required: true,
      label: { zh: "协议期限", en: "MNDA Term" },
    },
    {
      key: "保密期限",
      section: "keyterms",
      type: "string",
      required: true,
      label: { zh: "保密期限", en: "Confidentiality Term" },
    },
    {
      key: "适用法律",
      section: "keyterms",
      type: "string",
      required: true,
      label: { zh: "适用法律", en: "Governing Law" },
    },
    {
      key: "争议解决",
      section: "keyterms",
      type: "string",
      required: true,
      label: { zh: "争议解决", en: "Dispute Resolution" },
    },
    {
      key: "甲方公司名称",
      section: "parties",
      type: "string",
      required: true,
      label: { zh: "甲方公司名称", en: "Party A Company" },
    },
    {
      key: "乙方公司名称",
      section: "parties",
      type: "string",
      required: true,
      label: { zh: "乙方公司名称", en: "Party B Company" },
    },
    {
      key: "甲方签字人姓名",
      section: "parties",
      type: "string",
      required: false,
      label: { zh: "甲方签字人姓名", en: "Party A Signer Name" },
    },
    {
      key: "乙方签字人姓名",
      section: "parties",
      type: "string",
      required: false,
      label: { zh: "乙方签字人姓名", en: "Party B Signer Name" },
    },
    {
      key: "对标准条款的修订",
      section: "changes",
      type: "text",
      required: false,
      label: { zh: "对标准条款的修订", en: "Standard-Term Changes" },
    },
  ],
};

const MNDA_TEMPLATE = {
  doc_id: "mutual-nda",
  title: "双方保密协议",
  cover_page:
    "# 双方保密协议 · 封面页\n\n" +
    "| 条款 | 约定内容 |\n| --- | --- |\n" +
    '| 保密用途 | <span class="coverpage_link">保密用途</span> |\n' +
    '| 生效日期 | <span class="keyterms_link">生效日期</span> |\n' +
    '| 协议期限 | <span class="keyterms_link">协议期限</span> |\n' +
    '| 甲方 | <span class="coverpage_link">甲方公司名称</span> |\n' +
    '| 乙方 | <span class="coverpage_link">乙方公司名称</span> |',
  standard_terms:
    "# 双方保密协议 · 标准条款\n\n" +
    '为<span class="coverpage_link">保密用途</span>，双方披露保密信息。\n\n' +
    '本协议自<span class="keyterms_link">生效日期</span>起生效，有效期为' +
    '<span class="keyterms_link">协议期限</span>，保密义务在' +
    '<span class="keyterms_link">保密期限</span>内持续有效。\n\n' +
    '本协议适用<span class="keyterms_link">适用法律</span>，争议提交' +
    '<span class="keyterms_link">争议解决</span>。',
  manifest: MNDA_MANIFEST,
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
  mnda?: Record<string, unknown>;
};

function emptySnapshot(revision = 0): MockSnapshot {
  return {
    schema_version: "draft-state.v1",
    manifest_version: 1,
    doc_id: "mutual-nda",
    revision,
    fields: Object.fromEntries(
      MNDA_MANIFEST.fields.map((field) => [
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
  snapshot.fields.保密用途 = {
    key: "保密用途",
    status: "pending_confirmation",
    value: "评估融资合作",
    revision: 0,
    provenance: [
      {
        patch_id: "legacy-migration",
        source: "system",
        operation: "legacy_unverified",
        value: "评估融资合作",
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
    if (field.status === "confirmed" && typeof field.value === "string") {
      values[key] = field.value;
    }
  }
  return values;
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
        field.conflict = { base_value: field.value, proposed_value: op.value ?? "" };
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

async function installMockBackend(page: Page, options: { legacy?: boolean } = {}) {
  const events: { patches: MockPatchBody[]; puts: unknown[] } = {
    patches: [],
    puts: [],
  };
  let snapshot: MockSnapshot | null = options.legacy ? legacySnapshot() : null;
  let doc = {
    id: 1,
    doc_id: "mutual-nda",
    title: "MNDA draft",
    state: (options.legacy
      ? {
          chat: [{ role: "user", content: "旧草稿" }],
          mnda: { purpose: "评估融资合作" },
          fields: { 保密用途: "评估融资合作" },
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
        body: JSON.stringify(options.legacy ? [doc] : []),
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
      const unresolved = MNDA_MANIFEST.fields
        .filter((field) => field.required)
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
            "attachment; filename=agreement.docx; filename*=UTF-8''MNDA-20260803.docx",
        },
        body: "PK-mocked-docx",
      });
    },
  );

  await page.route(/\/api\/documents\/1$/, async (route) => {
    if (route.request().method() === "PUT") {
      events.puts.push(await route.request().postDataJSON());
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
  assistant = "已记录。还需要补充什么？",
) {
  await page.route("**/api/chat", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        assistant_message: assistant,
        selected_doc_id: "mutual-nda",
        mnda_updates: {},
        field_updates: fieldUpdates,
        done: false,
      }),
    }),
  );
}

async function startMndaChat(
  page: Page,
  fieldUpdates: Record<string, string>,
) {
  await mockChat(page, fieldUpdates);
  await page.goto("/");
  await page.getByLabel(/输入消息/).fill("我要起草双方保密协议");
  await page.getByRole("button", { name: /^发送$/ }).click();
  await expect(page.getByText("已记录。还需要补充什么？")).toBeVisible();
}

async function confirmField(page: Page, label: RegExp, value?: string) {
  const input = page.getByLabel(label);
  if (value !== undefined) await input.fill(value);
  const button = input.locator("xpath=ancestor::div[1]").getByRole("button", {
    name: "确认",
  });
  await expect(button).toBeEnabled();
  await button.click();
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

test.describe("MNDA document-state kernel adoption", () => {
  test("chat field updates are submitted as LLM proposals and render pending", async ({
    page,
  }) => {
    const events = await installMockBackend(page);
    await startMndaChat(page, { 保密用途: "评估融资合作" });

    expect(events.patches[0]).toMatchObject({
      source: "llm",
      base_revision: 0,
      operations: [{ op: "propose", key: "保密用途", value: "评估融资合作" }],
    });
    await expect(page.getByText("评估融资合作")).toBeVisible();
    await expect(page.getByText("待确认")).toBeVisible();
    await expect(page.getByRole("button", { name: /下载 DOCX/ })).toBeDisabled();
    await expect.poll(() => events.puts.length).toBeGreaterThanOrEqual(1);
    expect((events.puts.at(-1) as { state?: { fields?: unknown } }).state?.fields)
      .toBeUndefined();
  });

  test("form confirmation writes through field-patches", async ({ page }) => {
    const events = await installMockBackend(page);
    await startMndaChat(page, { 保密用途: "评估融资合作" });

    await page.getByRole("tab", { name: "手动编辑" }).click();
    await page.getByRole("button", { name: "确认" }).nth(0).click();

    await expect(page.getByText("已确认").first()).toBeVisible();
    expect(events.patches[1]).toMatchObject({
      source: "form",
      base_revision: 1,
      operations: [{ op: "confirm", key: "保密用途", value: "评估融资合作" }],
    });
  });

  test("conflicts show base and candidate and can be resolved", async ({ page }) => {
    const events = await installMockBackend(page);
    await startMndaChat(page, { 保密用途: "评估融资合作" });
    await page.getByRole("tab", { name: "手动编辑" }).click();
    await page.getByRole("button", { name: "确认" }).nth(0).click();

    await mockChat(page, { 保密用途: "评估技术合作" }, "候选值已记录。还要补充什么？");
    await page.getByRole("tab", { name: "AI 对话" }).click();
    await page.getByLabel(/输入消息/).fill("改成技术合作");
    await page.getByRole("button", { name: /^发送$/ }).click();

    await expect(page.getByText("冲突")).toBeVisible();
    await expect(page.getByText("当前: 评估融资合作")).toBeVisible();
    await expect(page.getByText("候选: 评估技术合作")).toBeVisible();
    await page.getByRole("tab", { name: "手动编辑" }).click();
    await page.getByRole("button", { name: "拒绝" }).click();
    await expect(page.getByText("冲突")).toHaveCount(0);
    expect(events.patches.some((patch) => patch.operations[0].op === "reject"))
      .toBe(true);
  });

  test("download gate unlocks only after all required fields are confirmed", async ({
    page,
  }) => {
    await installMockBackend(page);
    await startMndaChat(page, {
      保密用途: "评估融资合作",
      生效日期: "2026-08-01",
      协议期限: "自生效日期起 2 年",
      保密期限: "自生效日期起 5 年",
      适用法律: "中华人民共和国法律",
      争议解决: "上海仲裁委员会按其仲裁规则进行仲裁",
      甲方公司名称: "甲方科技有限公司",
      乙方公司名称: "乙方科技有限公司",
    });
    await page.getByRole("tab", { name: "手动编辑" }).click();

    const download = page.getByRole("button", { name: /下载 DOCX/ });
    await expect(download).toBeDisabled();

    await confirmField(page, /保密用途/);
    await confirmField(page, /生效日期/);
    await confirmField(page, /协议期限/);
    await confirmField(page, /保密期限/);
    await confirmField(page, /适用法律/);
    await confirmField(page, /争议解决/);
    await confirmField(page, /甲方公司名称/);
    await confirmField(page, /乙方公司名称/);

    await expect(download).toBeEnabled();
    const downloadEvent = page.waitForEvent("download");
    await download.click();
    const savedFile = await downloadEvent;
    expect(savedFile.suggestedFilename()).toBe("MNDA-20260803.docx");
  });

  test("legacy state.mnda drafts restore as pending kernel fields", async ({
    page,
  }) => {
    await page.addInitScript(() => {
      window.localStorage.setItem("prelegal:activeDocId", "1");
    });
    await installMockBackend(page, { legacy: true });

    await page.goto("/");

    await expect(page.getByText("旧草稿")).toBeVisible();
    await expect(page.getByText("评估融资合作")).toBeVisible();
    await expect(page.getByText("待确认")).toBeVisible();
    await page.getByRole("tab", { name: "手动编辑" }).click();
    await page.getByRole("button", { name: "确认" }).nth(0).click();
    await expect(page.getByText("已确认").first()).toBeVisible();
  });
});
