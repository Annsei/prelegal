# Testing

The Mutual NDA generator has three test layers plus a manual checklist. All
layers are green on the current branch.

## Automated

| Layer       | Tool                                       | Files                                                                                  | Run                    |
| ----------- | ------------------------------------------ | -------------------------------------------------------------------------------------- | ---------------------- |
| Unit        | Vitest + happy-dom                         | `lib/*.test.ts`                                                                        | `npm test`             |
| Component   | Vitest + React Testing Library + happy-dom | `components/*.test.tsx`                                                                 | `npm test`             |
| E2E         | Playwright (chromium)                      | `e2e/*.spec.ts`                                                                        | `npm run test:e2e`     |

- First E2E run: `npm run test:e2e:install` to fetch a matching chromium binary.
- `npm run test:watch` is available for TDD.
- Current counts: **18 unit** + **20 component** = **38** Vitest tests; **7**
  Playwright tests. Run the commands above to see the live totals.

## Manual checklist

Automated tests can't cover printed-PDF fidelity, cross-browser print quirks,
or visual layout. Work through this list before shipping a release.

### Setup
- [ ] `npm install`
- [ ] `npm run dev` — dev server should boot within ~2s on `http://localhost:3000`

### Form ↔ preview sync (happy path, English UI)
- [ ] Click **English** in the header; all form labels switch to English
- [ ] Empty required fields show a red `[missing]` pill in the preview
- [ ] Type into **Purpose** — the new text appears in Section 1 (Introduction) and Section 2 (Use and Protection) of the Standard Terms, and under the Purpose heading on the cover page
- [ ] Pick an **Effective Date** — formatted as `Month D, YYYY` in the cover page and Section 5
- [ ] Fill **Governing Law** / **Jurisdiction** — both appear in the cover page and Section 9 (Governing Law and Jurisdiction)
- [ ] Fill all four **Party 1** and **Party 2** fields — the signature table rows populate
- [ ] Fill **Modifications** — appears under "MNDA Modifications" on the cover page

### MNDA Term / Term of Confidentiality radio logic
- [ ] Default: **Expires 1 year(s)** — cover page shows a filled checkbox next to the first option, Section 5 contains "1 year(s) from the Effective Date"
- [ ] Select **Continues until terminated** — cover page checkbox flips, Section 5 body says "term until terminated"
- [ ] Type `5` into the MNDA-term year input while "Continues" is selected — radio auto-flips back to **Expires** and Section 5 shows "5 year(s)"
- [ ] Repeat the flow for **Term of Confidentiality** / **In perpetuity**

### Localization
- [ ] Switch back to **中文** — all form labels (including section headers and help text) return to Chinese
- [ ] The document preview (right side) stays English regardless of UI locale — this is intentional; translating the legal text changes its meaning

### PDF download
- [ ] Click **下载 PDF** / **Download PDF** — browser print dialog opens
- [ ] In the print dialog, choose **Save as PDF** (macOS) or **Microsoft Print to PDF** (Windows) and save the file
- [ ] Open the PDF: header / form / download button must all be absent
- [ ] Cover page appears on page 1 with the signature table intact
- [ ] Standard Terms follow and flow across multiple pages without clipping — **verify all 11 sections are present and the final "Common Paper … CC BY 4.0" attribution line appears at the end**
- [ ] Page margins are ~18mm top/bottom, ~16mm left/right (A4)
- [ ] `.filled` highlight (yellow) and `.missing` highlight (pink) are suppressed in the PDF (missing still shows in red text for visibility)

### Cross-browser print sanity
Repeat the **PDF download** section in each browser you support:
- [ ] Chrome / Chromium
- [ ] Safari (print-dialog behavior differs slightly; verify multi-page flow)
- [ ] Firefox

### Timezone regression
`formatEffectiveDate` parses the ISO date as local calendar time to avoid a UTC
off-by-one bug. Sanity check after any change to that helper:
- [ ] Set system timezone to `Pacific/Honolulu` (UTC−10), pick `2026-01-01`, reload
- [ ] Preview shows **January 1, 2026** — not December 31, 2025

### Responsive / zoom
- [ ] At ≥1024 px viewport, form and preview are side-by-side
- [ ] Below that threshold, form stacks above the preview (check on a phone-sized window)
- [ ] Increase browser zoom to 200 %: layout remains usable, no horizontal scroll

### Accessibility smoke test
- [ ] Tab through every form field — focus order is top-to-bottom, visible focus ring on each
- [ ] Every `<input>` / `<textarea>` has an associated `<label>` (verify via devtools)
- [ ] Language toggle button reads its current target ("English" when zh is active, "中文" when en is active) — works with screen reader or browser's read-aloud

### Edge cases
- [ ] Paste a very long Purpose (~2000 chars) — text wraps; no layout breakage; still prints correctly
- [ ] Enter `0` for MNDA Term years — cover page shows "0 year(s)" (no crash); user-visible behavior is acceptable
- [ ] Clear all fields back to defaults — preview updates immediately; every field reverts to its red placeholder
