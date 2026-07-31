# Testing

The supported end-to-end drafting flows are manifest-driven CSA and MNDA. Both
use the document-state kernel for field proposals, explicit confirmation,
conflict resolution, preview, and download gating. Other catalog documents still
render through the fallback template preview until they receive a manifest.

## Automated

| Layer | Tool | Files | Run |
| --- | --- | --- | --- |
| Unit | Vitest + happy-dom | `lib/*.test.ts`, `components/*.test.tsx` | `npm test -- --run` |
| E2E | Playwright (chromium) | `e2e/*.spec.ts` | `npx playwright test` |
| Type/lint | Next.js / TypeScript / ESLint | app + component sources | `npm run lint`, `npx tsc --noEmit` |

- First E2E run: `npm run test:e2e:install` to fetch a matching chromium binary.
- `npm run test:watch` is available for TDD.
- Test totals move as flows are migrated; run the commands above for the live
  counts instead of relying on this file.

## Manual Checklist

Automated tests cover the main state-machine behavior. Manual release checks
focus on browser rendering, PDF print behavior, and copy clarity.

### Setup

- [ ] `npm install`
- [ ] `npm run dev` with `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`
- [ ] Backend running on `http://localhost:8000` with a writable test database

### Manifest Drafting

- [ ] Create a CSA draft; chat-extracted fields appear as pending, not confirmed
- [ ] Confirm a pending CSA field; preview and download gate use the confirmed value
- [ ] Propose a different value for a confirmed CSA field; conflict shows base and candidate
- [ ] Resolve the conflict by keeping the base value, then by accepting the candidate
- [ ] Repeat the same checks for MNDA
- [ ] Open a legacy MNDA draft with `state.mnda`; values migrate to pending
  `legacy_unverified` fields and remain visible for confirmation
- [ ] Non-field autosave changes such as chat history and title do not remove or
  roll back `draft_state`

### Preview

- [ ] Manifest cover-page fields are grouped by manifest section
- [ ] Pending, confirmed, conflict, and missing states are visually distinct
- [ ] Standard terms render after the Cover Page
- [ ] Term-reference spans show defined/missing state without inline value
  substitution
- [ ] The document text stays Simplified Chinese regardless of UI locale

### Download Gate

- [ ] Required missing fields keep the download button disabled
- [ ] Conditional required fields are listed in the inline blocker message
- [ ] Confirming all required fields unlocks download readiness
- [ ] Attempted downloads blocked by the server show the missing field labels

### PDF Print

- [ ] Click **下载 PDF** / **Download PDF** and save from the browser print dialog
- [ ] Header, form, sidebar, and download controls are absent from the printed output
- [ ] Cover Page appears before Standard Terms
- [ ] Standard Terms flow across pages without clipping
- [ ] Page margins are suitable for A4 printing
- [ ] Missing/pending/conflict visual markers do not obscure the legal text

### Responsive And Accessibility

- [ ] At desktop width, sidebar, chat/form, and preview are usable side-by-side
- [ ] On a phone-sized viewport, the layout stacks without horizontal scroll
- [ ] Browser zoom at 200% remains usable
- [ ] Tab order reaches chat input, tabs, form controls, conflict actions, and download
- [ ] Every form control has an accessible label or aria label
