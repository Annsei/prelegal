# ADR 0001: Product Scope And Template Baseline

Date: 2026-07-29

Status: Accepted

## Context

Prelegal has moved from earlier Common Paper-oriented assumptions to a PRC-law
Simplified Chinese template library. Product, pricing, and expansion decisions
must not mix those two baselines.

## Decision

The formal product line in this repository is PRC-law Simplified Chinese legal
drafting unless a later ADR changes that scope.

Current document baselines:

| Document | Product status | Governing law | Language | Template source and version | Manifest / implementation version | Legal review status | Legal review responsibility |
| --- | --- | --- | --- | --- | --- | --- | --- |
| MNDA (`mutual-nda`) | Prototype and regression sample. It is catalogued as available and is now served by the manifest-driven document-state kernel, but it is not a lawyer-reviewed paid product. | PRC law | Simplified Chinese | Prelegal first-party, AI-assisted template v1.0 (`templates/templates.json`, `source.origin=prelegal`, `source.version=1.0`) | Manifest version 1 (`templates/manifests/mutual-nda.json`). Server kernel schema `draft-state.v1`; PL-17 retires the bespoke MNDA form/preview/template path and migrates legacy typed `state.mnda` values to pending `legacy_unverified` field states. | Not lawyer-reviewed in this repo. | unassigned |
| CSA (`cloud-service-agreement`) | Manifest pipeline pilot and regression sample. It is catalogued as available and its chat, form, preview, download gate, and auto-save path are authoritative kernel adopters. | PRC law | Simplified Chinese | Prelegal first-party, AI-assisted template v1.0 (`templates/templates.json`, `source.origin=prelegal`, `source.version=1.0`) | Manifest version 2 (`templates/manifests/cloud-service-agreement.json`). Server kernel schema `draft-state.v1`; authoritative CSA adoption landed in PL-15 with PL-16 polish. | Not lawyer-reviewed in this repo. | unassigned |

Because legal review responsibility is unassigned for both documents, formal
paid legal-document claims and any "lawyer review" product wording remain
blocked. The existing disclaimer remains mandatory: these are draft templates
for review by a qualified lawyer, not legal advice.

PSA/SOW must stay split into two separate concepts:

- The repository contains a PRC-law Simplified Chinese PSA candidate
  (`professional-services-agreement`) with catalog status `planned` and
  Prelegal template source v1.0. It is not a production pricing proof until its
  manifest, support status, and legal review responsibility are explicit.
- Any Common Paper English PSA, English-market pricing analysis, or
  Common-Paper-derived workflow is a research or architecture fixture only. It
  is not the production PSA/SOW template for this PRC-law Chinese product line.

Every template that moves toward production support must identify:

- governing law and language;
- template source and source version;
- manifest version or implementation path;
- legal review status and responsible party;
- whether it is a supported product document, prototype, regression sample, or
  architecture fixture.

## Consequences

Pipeline work may use PSA to reason about extensibility, but PSA productization
and pricing remain blocked until the law, language, source, and legal review
baseline is explicit.

The core pipeline should preserve template metadata and review status so that
future paid experiences do not present planned or unreviewed documents as
complete products.
