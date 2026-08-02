# Legal Document Templates

This directory holds the PRC-law Chinese agreement templates that Prelegal
customizes for users. Each template's source is recorded in
`templates.json`; official source captures and provenance live under
`sources/<doc_id>/`.

Most current templates remain first-party Prelegal 范本 v1.0, AI-assisted and
not lawyer-reviewed. `professional-services-agreement` and
`data-processing-agreement` use 2025 official model-contract baselines;
see [ADR 0002](../docs/adr/0002-official-template-baseline.md) for the full
mapping and adaptation limits. The legacy `LICENSE` remains in the repository
for its historical Common Paper material and does not describe the official
model-contract sources.

## Layout

```
templates/
├── LICENSE                 CC BY 4.0 attribution for the upstream templates
├── README.md               this file
├── templates.json          machine-readable manifest of all templates
├── sources/<template-id>/  immutable official source capture + provenance
└── <template-id>/          one directory per template
    └── *.md                one or more Markdown files (cover page, standard terms, etc.)
```

## Manifest (`templates.json`)

`templates.json` is the authoritative index of the dataset. For each template
it records:

- `id` — stable slug used as the directory name
- `title`, `description`, `category`
- `files` — the Markdown files that make up the template, each tagged with a
  `type` (e.g. `cover_page`, `standard_terms`)
- `source` — the first-party or official baseline, version/number, issuer, URL,
  and acquisition metadata needed to audit a template

## Refreshing the dataset

Do not overwrite a file below `sources/`: it is the immutable capture against
which product adaptations are reviewed. A new official revision needs a new
capture, provenance record, and ADR update before a product template changes.
