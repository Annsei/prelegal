import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  DocumentSidebar,
  parseDocumentTimestamp,
  relativeTime,
} from "./DocumentSidebar";

describe("document timestamp compatibility", () => {
  it.each([
    ["2026-08-13 12:00:00", Date.UTC(2026, 7, 13, 12, 0, 0)],
    ["2026-08-13T12:00:00Z", Date.UTC(2026, 7, 13, 12, 0, 0)],
    ["2026-08-13T20:00:00+08:00", Date.UTC(2026, 7, 13, 12, 0, 0)],
  ])("parses %s as the same UTC instant", (raw, expected) => {
    expect(parseDocumentTimestamp(raw)).toBe(expected);
  });

  it("returns null for invalid timestamps", () => {
    expect(parseDocumentTimestamp("not-a-date")).toBeNull();
  });

  it("shows legacy UTC timestamps as now in positive and negative offsets", () => {
    const now = Date.UTC(2026, 7, 13, 12, 0, 0);
    const originalTz = process.env.TZ;
    try {
      for (const timezone of ["Asia/Shanghai", "America/New_York"]) {
        process.env.TZ = timezone;
        expect(relativeTime("2026-08-13 12:00:00", "zh", now)).toBe("现在");
        expect(relativeTime("2026-08-13 12:00:00", "en", now)).toBe("now");
      }
    } finally {
      process.env.TZ = originalTz;
    }
  });

  it("renders a safe empty label for invalid API values", () => {
    render(
      <DocumentSidebar
        locale="en"
        documents={[
          {
            id: 1,
            doc_id: "mutual-nda",
            title: "Invalid timestamp",
            created_at: "bad",
            updated_at: "bad",
          },
        ]}
        activeId={1}
        catalogTitleFor={() => "MNDA"}
        onSelect={vi.fn()}
        onCreate={vi.fn()}
      />,
    );
    expect(screen.getByText("MNDA")).toBeInTheDocument();
  });
});
