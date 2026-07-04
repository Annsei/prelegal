"""Cover-page field manifests.

A manifest (templates/manifests/<doc_id>.json) declares the typed
cover-page fields for one catalog document: canonical key (the exact
term name the template body references), zh/en labels, type, required
flag, an example, and alias span texts (possessives/plurals). One data
file drives all four consumers:

- the LLM prompt (which fields to collect) and structured-output schema,
- the manual-edit form in the frontend,
- the rendered Cover Page in the preview,
- body-reference highlighting (defined vs missing terms).

Documents without a manifest fall back to free-form field collection.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

# templates/manifests lives at the repo root. From this file:
# backend/app/manifests.py → backend/app → backend → repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_MANIFESTS_DIR = _REPO_ROOT / "templates" / "manifests"


@cache
def load_manifest(doc_id: str) -> dict[str, Any] | None:
    """Load a document's manifest, or None if it doesn't have one.

    doc_id can come from URL paths and request bodies — refuse anything
    that isn't a plain catalog id so it can't traverse out of the
    manifests directory.
    """
    if not doc_id or not doc_id.replace("-", "").isalnum():
        return None
    try:
        raw = json.loads((_MANIFESTS_DIR / f"{doc_id}.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) and raw.get("fields") else None


def manifest_field_keys(manifest: dict[str, Any]) -> list[str]:
    """Canonical field keys in declaration order."""
    return [
        field["key"]
        for field in manifest.get("fields", [])
        if isinstance(field, dict) and isinstance(field.get("key"), str)
    ]
