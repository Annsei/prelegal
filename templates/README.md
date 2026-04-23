# Legal Document Templates

This directory holds the seed dataset of legal agreement templates that the
prelegal system will customize for users.

All templates are sourced from [Common Paper](https://commonpaper.com/) (via
the [CommonPaper GitHub organization](https://github.com/CommonPaper)) and are
distributed under the Creative Commons Attribution 4.0 International License
(CC BY 4.0). See `LICENSE` in this directory for full attribution.

## Layout

```
templates/
├── LICENSE                 CC BY 4.0 attribution for the upstream templates
├── README.md               this file
├── templates.json          machine-readable manifest of all templates
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
- `source.repo` and `source.commit` — the upstream Common Paper repository and
  the exact commit that each local file was copied from, so the dataset can be
  refreshed deterministically

## Refreshing the dataset

To pull newer upstream revisions, re-download the files listed in
`templates.json` from the corresponding `source.repo` at the `main` branch and
update the `source.commit` / `source.commit_date` fields to the new HEAD.
