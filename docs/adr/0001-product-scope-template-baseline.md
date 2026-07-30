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

MNDA and CSA remain the current supported regression documents:

- MNDA is a complete bespoke vertical slice and must not regress while it is
  waiting for manifest migration.
- CSA is the first manifest-driven document and the current pipeline pilot.

PSA/SOW is a planned expansion candidate, but not yet a production pricing
proof. A Common Paper PSA or English-market pricing analysis may be used as a
technical or commercial research fixture only; it is not a launch-ready product
template for this PRC-law product line.

Every template that moves toward production support must identify:

- governing law and language;
- template source and source version;
- manifest version;
- legal review status and responsible party;
- whether it is a product-supported document or an architecture fixture.

## Consequences

PL-14 and later pipeline work may use PSA to reason about extensibility, but PSA
productization and pricing remain blocked until the law, language, source, and
legal review baseline is explicit.

The core pipeline should preserve template metadata and review status so that
future paid experiences do not present planned or unreviewed documents as
complete products.
