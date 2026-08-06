import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Disclaimer } from "./Disclaimer";

const ZH_FULL =
  "本文档为 AI 生成的草稿，仅供参考，不构成法律意见。正式签署前请交由执业律师审核。";
const ZH_SHORT = "AI 草稿，不构成法律意见；正式签署前请执业律师审核。";
const EN_FULL =
  "This document is an AI-generated draft for reference only and does not constitute legal advice. Have a licensed lawyer review it before formal execution.";

describe("Disclaimer", () => {
  it("uses the short Chinese notice in the banner and the full text in the footer", () => {
    render(
      <>
        <Disclaimer locale="zh" variant="banner" />
        <Disclaimer locale="zh" variant="footer" />
      </>,
    );

    expect(screen.getByText(ZH_SHORT)).toBeInTheDocument();
    expect(screen.getByText(ZH_FULL)).toBeInTheDocument();
  });

  it("keeps all three safeguards in English and compact copy", () => {
    const { rerender } = render(<Disclaimer locale="en" variant="banner" />);
    expect(screen.getByText(/AI draft, not legal advice/i)).toHaveTextContent(
      /licensed lawyer.*before signing/i,
    );

    rerender(<Disclaimer locale="en" variant="footer" />);
    expect(screen.getByText(EN_FULL)).toBeInTheDocument();

    rerender(<Disclaimer locale="en" variant="compact" />);
    expect(screen.getByText(/AI draft, not legal advice/i)).toHaveTextContent(
      /licensed lawyer.*before signing/i,
    );
  });
});
