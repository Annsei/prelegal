# ADR 0002: Official Template Baseline

Date: 2026-08-01

Status: Accepted

## Context

The original 11-document library was labelled `Prelegal 范本 v1.0` and
AI-assisted. The product now retains the captured official source text before
any product adaptation, so every changed template can be reviewed against a
stable baseline. This ADR supplements, rather than replaces, ADR 0001's PRC
law, Simplified Chinese, and lawyer-review boundaries.

Official model contracts are texts for parties to refer to when contracting
under Article 470 of the Civil Code. Their authority is stronger than a
first-party draft, but they are not legal advice or a substitute for a lawyer's
review. The existing three product disclaimers remain mandatory. Legal-review
responsibility is `unassigned`; that continues to block paid-product and
"lawyer review" claims.

## Baseline Map

| Catalog document | Baseline | Authority | Replacement status |
| --- | --- | --- | --- |
| `mutual-nda` | Prelegal 范本 v1.0, AI-assisted | First-party only | No identified official NDA baseline; retained as prototype/regression sample |
| `cloud-service-agreement` | Prelegal 范本 v1.0, AI-assisted | First-party only | No identified official SaaS/CSA baseline; retained as kernel pilot/regression sample |
| `design-partner-agreement` | Prelegal 范本 v1.0, AI-assisted | First-party only | Final product baseline by product decision; manifest-enabled in PL-21 batch 2 |
| `service-level-agreement` | Prelegal 范本 v1.0, AI-assisted | First-party only | Final product baseline by product decision; manifest-enabled in PL-20 batch 1 |
| `professional-services-agreement` | SAMR `委托合同（示范文本）` GF-2025-1001, July 2025 | Official model contract | Replaced in this batch; original capture at `templates/sources/professional-services-agreement/` |
| `data-processing-agreement` | National Data Administration and SAMR `数据委托处理服务合同（示范文本）` GF-2025-2616, July 2025 | Official model contract | Replaced in this batch; original capture at `templates/sources/data-processing-agreement/` |
| `software-license-agreement` | Prelegal 范本 v1.0, AI-assisted | First-party only | Final product baseline by product decision; manifest-enabled in PL-20 batch 1. The previously identified Ministry of Science and Technology text is not a product dependency. |
| `partnership-agreement` | Prelegal 范本 v1.0, AI-assisted | First-party only | Final product baseline by product decision; manifest-enabled in PL-21 batch 2 |
| `pilot-agreement` | Prelegal 范本 v1.0, AI-assisted | First-party only | Final product baseline by product decision; manifest-enabled in PL-20 batch 1 |
| `business-associate-agreement` | Prelegal 范本 v1.0, AI-assisted | First-party only | Final product baseline by product decision; manifest-enabled in PL-21 batch 2 |
| `ai-addendum` | Prelegal 范本 v1.0, AI-assisted | First-party only | Final product baseline by product decision; manifest-enabled in PL-21 batch 2 |

The national model-contract library also contains `数据提供合同`、`数据融合开发合同`
and `数据中介服务合同（GF-2025-2618）`. They are possible future baselines,
not part of this batch.

The data-processing replacement is for domestic data and personal-information
processing. It is not the CAC personal-information outbound standard contract.
Outbound transfers remain subject to their own statutory route and are out of
scope for this template.

## Prelegal v1.0 Final-Baseline Decision

The product owner has decided that every remaining catalog document uses its
existing Prelegal 范本 v1.0 text as the final product baseline. The decision
removes any requirement to find, wait for, or archive an external official
model contract before enabling a remaining document in the manifest pipeline.

This is a product-delivery decision, not a claim that first-party templates
are official or lawyer-reviewed. The existing three lawyer-review disclaimers
remain mandatory, legal-review responsibility remains `unassigned`, and the
decision does not authorize paid-product or "lawyer review" claims. The three
documents enabled in PL-20 batch 1 are `service-level-agreement`,
`software-license-agreement`, and `pilot-agreement`. PL-21 batch 2 completes
the catalog by enabling `design-partner-agreement`, `partnership-agreement`,
`business-associate-agreement`, and `ai-addendum`, without a source-provenance
prerequisite.

## Captured Sources

The following raw captures are committed without alteration before the
product-template commit. Their `PROVENANCE.md` files record the official View
URL, issuer, number, acquisition date, file name, and capture limitation.

- `templates/sources/professional-services-agreement/GF-2025-1001-委托合同-原文捕获.txt`
- `templates/sources/data-processing-agreement/GF-2025-2616-数据委托处理服务合同-原文捕获.txt`

Both 2025 texts already cite the Civil Code. No obsolete `合同法` reference was
present, so this batch makes no legal-basis substitution.

## Product Adaptations

### Common structural changes

1. The signed party-information blocks, blank lines, tables, and checkbox
   selections are represented as named cover-page fields. The body references
   each field by a `coverpage_link`, `orderform_link`, or `keyterms_link` span;
   it never substitutes a value inline.
2. Related blank cells are grouped into a single typed text field where the
   official form uses a repeated party block or an expandable table. This keeps
   the official information requirement while making a chat/form workflow
   usable. The cover-page label and hint identify each original component.
3. Official website navigation, download controls, copyright footer, and
   website risk-tip panels are retained verbatim in the source capture but are
   not contract clauses and are therefore not rendered in the product body.
   The official contract title, party block, preamble, numbered articles, and
   signature block remain in the product template.

### `professional-services-agreement`

1. The product title is `专业服务协议`; the body identifies its official
   `委托合同（GF-2025-1001）` baseline. This is a catalog classification only;
   no SOW, intellectual-property, liability, or other substantive clause was
   added beyond the official text.
2. The two official party-information blocks are split into party name plus a
   combined identity/contact field. The original fields (document type and
   number, address, representative, contact, telephone, mailing address,
   postal code, and email) remain required by that cover-page field's hint.
3. Article 1's special/general checkbox, Article 2 choices, Articles 4-6
   commercial blanks, Article 7 ownership choices, and Articles 8 and 11-17
   blanks are converted into named fields. `委托方式` conditionally requires
   the corresponding special or general scope; all other choices use a
   constrained explanatory string field.
4. Article 4's incomplete-work alternatives, Article 5 payment rows, and
   Article 6 acceptance alternatives are grouped into their corresponding
   cover-page arrangement field. The official rule, remedies, and allocation
   remain unchanged.

### `data-processing-agreement`

1. The catalog display name is changed from `个人信息委托处理协议` to
   `数据/个人信息委托处理协议` to match the official data-processing scope;
   it remains a domestic data and personal-information processing document.
2. The official party blocks are split into name and combined identity/contact
   fields. Article 1 source-data blanks, Article 2-3 result/process-data tables
   and rights selections, and Article 4-10 data-processing blanks are moved to
   named cover-page fields.
3. The official checkbox collections for processing and delivery are represented
   by explanatory string fields. Selecting `其他` processing conditionally
   requires its description; selecting electronic or physical delivery
   conditionally requires the corresponding delivery arrangement.
4. Article 8 quality-remediation blanks, Article 9 calculation/payment/invoice
   blanks, Articles 10 and 13-18 blanks, and the signing location are represented
   by named fields. No new outbound-transfer, security, liability, or personal
   information obligation was added; the official cross-border clause remains
   unchanged.

## Consequences

`professional-services-agreement` and `data-processing-agreement` are
manifest-backed kernel documents. Their LLM proposals, form confirmations,
preview, term-reference highlighting, and download gate share the existing
server-owned field-state contract. This is technical availability, not lawyer
approval or authorization to make paid legal-document claims.
