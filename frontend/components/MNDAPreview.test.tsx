import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MNDAPreview } from "./MNDAPreview";
import { INITIAL_STATE, type MndaState } from "@/lib/mndaState";

function renderPreview(overrides: Partial<MndaState> = {}) {
  const state: MndaState = { ...INITIAL_STATE, ...overrides };
  return render(<MNDAPreview value={state} />);
}

describe("MNDAPreview", () => {
  it("renders the document header and the template notice", () => {
    renderPreview();
    expect(
      screen.getByRole("heading", { name: "双方保密协议", level: 1 }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Prelegal 双方保密协议范本 v1.0/),
    ).toBeInTheDocument();
    expect(screen.getByText(/签署前请由执业律师审核/)).toBeInTheDocument();
  });

  it("substitutes {{purpose}} in the standard-terms body", () => {
    renderPreview({ purpose: "评估战略合作可能性。" });
    // The phrase should appear in the standard terms (at least twice, per
    // 协议构成 and 保密信息的使用与保护 sections).
    const matches = screen.getAllByText(/评估战略合作可能性。/);
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });

  it("substitutes {{governingLaw}} and {{jurisdiction}} in the dispute-resolution section", () => {
    renderPreview({
      governingLaw: "中华人民共和国法律",
      jurisdiction: "北京仲裁委员会按其仲裁规则进行仲裁",
    });
    // Cover page + section body each render the value at least once.
    expect(
      screen.getAllByText("中华人民共和国法律").length,
    ).toBeGreaterThanOrEqual(2);
    expect(
      screen.getAllByText("北京仲裁委员会按其仲裁规则进行仲裁").length,
    ).toBeGreaterThanOrEqual(2);
  });

  it("reflects mndaTerm and confidentialityTerm in the term section (regression)", () => {
    // Regression guard: the term section used to hard-code these strings.
    // They must follow the form state.
    renderPreview({
      mndaTermMode: "expires",
      mndaTermYears: 7,
      confidentialityMode: "perpetual",
    });
    // mndaTerm renders as "自生效日期起 7 年"
    expect(screen.getByText(/自生效日期起 7 年/)).toBeInTheDocument();
    // confidentialityTerm renders as "永久" (cover page checkbox row + body)
    expect(screen.getAllByText(/永久/).length).toBeGreaterThan(0);
  });

  it("renders formatted effectiveDate in both cover page and the term section", () => {
    renderPreview({ effectiveDate: "2026-01-01" });
    // Cover-page header + term-section body each have their own rendering.
    const matches = screen.getAllByText("January 1, 2026");
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });

  it("renders confidentialityYears in the cover-page checklist", () => {
    renderPreview({
      confidentialityMode: "years",
      confidentialityYears: 12,
    });
    expect(screen.getAllByText(/12 年/).length).toBeGreaterThan(0);
  });

  it("emits .missing placeholders when party fields are empty", () => {
    // INITIAL_STATE leaves both parties blank; without any overrides, the 8
    // 甲方/乙方 fields alone must produce at least 8 missing pills.
    const { container } = renderPreview();
    const missingInTable = container.querySelectorAll(
      "table .missing",
    ).length;
    expect(missingInTable).toBeGreaterThanOrEqual(8);
  });

  it("emits no .missing pills in the signature table when both parties are fully filled", () => {
    const filled = {
      company: "示例科技（北京）有限公司",
      signerName: "张三",
      signerTitle: "法定代表人",
      noticeAddress: "legal@example.com.cn",
    };
    const { container } = renderPreview({
      party1: filled,
      party2: { ...filled, company: "示例云计算（上海）有限公司" },
    });
    expect(container.querySelectorAll("table .missing").length).toBe(0);
  });

  it("shows filled party data in the signature table", () => {
    renderPreview({
      party1: {
        company: "示例科技（北京）有限公司",
        signerName: "张三",
        signerTitle: "首席执行官",
        noticeAddress: "zhangsan@example.com.cn",
      },
    });
    expect(screen.getByText("示例科技（北京）有限公司")).toBeInTheDocument();
    expect(screen.getByText("张三")).toBeInTheDocument();
    expect(screen.getByText("首席执行官")).toBeInTheDocument();
    expect(screen.getByText("zhangsan@example.com.cn")).toBeInTheDocument();
  });

  it("renders all 6 standard-row labels in the signature table", () => {
    renderPreview();
    const table = screen.getByRole("table");
    for (const label of [
      "签字",
      "姓名",
      "职务",
      "公司名称",
      "通知地址",
      "签署日期",
    ]) {
      expect(within(table).getByText(label)).toBeInTheDocument();
    }
  });

  it("renders the modifications cover-page field", () => {
    renderPreview({ modifications: "第五条不适用。" });
    expect(
      screen.getByRole("heading", { name: "对标准条款的修订" }),
    ).toBeInTheDocument();
    expect(screen.getByText("第五条不适用。")).toBeInTheDocument();
  });

  it("tags the root article with data-print-root for print CSS", () => {
    const { container } = renderPreview();
    const printRoot = container.querySelector("[data-print-root]");
    expect(printRoot).not.toBeNull();
    expect(printRoot?.tagName.toLowerCase()).toBe("article");
  });

  it("renders the standard-terms heading and all 11 section headings", () => {
    renderPreview();
    expect(
      screen.getByRole("heading", { name: "标准条款", level: 2 }),
    ).toBeInTheDocument();
    // Each numbered list item's leading <strong> should carry the section name.
    for (const heading of [
      "协议构成",
      "保密信息的使用与保护",
      "除外情形",
      "依法披露",
      "期限与终止",
      "返还与销毁",
      "权利保留",
      "不作保证",
      "违约责任",
      "适用法律与争议解决",
      "其他约定",
    ]) {
      expect(screen.getByText(new RegExp(`^${heading}。`))).toBeInTheDocument();
    }
  });
});
