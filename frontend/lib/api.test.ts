import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, documentsApi } from "@/lib/api";


describe("documentsApi.download", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the file blob and decodes an RFC 5987 filename", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(new Blob(["PK-test-docx"]), {
        status: 200,
        headers: {
          "Content-Type":
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          "Content-Disposition":
            "attachment; filename=agreement.docx; filename*=UTF-8''%E4%B8%AD%E6%96%87%E5%8D%8F%E8%AE%AE-20260803.docx",
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await documentsApi.download("token", 42, "docx");

    expect(result.filename).toBe("中文协议-20260803.docx");
    expect(await result.blob.text()).toBe("PK-test-docx");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/documents/42/download?format=docx",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer token" }),
      }),
    );
  });

  it("preserves structured 409 readiness details", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: {
              validation_errors: [{ kind: "download_blocked" }],
              unresolved_required_fields: ["客户"],
            },
          }),
          {
            status: 409,
            headers: { "Content-Type": "application/json" },
          },
        ),
      ),
    );

    await expect(documentsApi.download("token", 42, "pdf")).rejects.toMatchObject<
      Partial<ApiError>
    >({
      status: 409,
      detail: {
        detail: {
          unresolved_required_fields: ["客户"],
        },
      },
    });
  });
});
