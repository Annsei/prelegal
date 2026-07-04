"""GET /api/templates/{doc_id} — serve the markdown template for a document.

The frontend uses this for the generic preview pane: the chat assistant
picks a `selected_doc_id` from the catalog, the frontend fetches the
matching standard terms (and cover page if present), and renders them
client-side with AI-collected key terms substituted in.

Reads from `templates/templates.json` at the repo root, the same index the
catalog references via use_when. We keep the index in JSON (not Python) so
the templates package and its provenance metadata stay self-describing.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.manifests import load_manifest

router = APIRouter(prefix="/templates")

# templates/templates.json lives at the repo root. From this file:
# backend/app/routes/templates.py → backend/app/routes → backend/app →
# backend → repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_TEMPLATES_DIR = _REPO_ROOT / "templates"
_TEMPLATES_INDEX = _TEMPLATES_DIR / "templates.json"


@lru_cache(maxsize=1)
def _index() -> dict[str, dict]:
    """Map `doc_id → template entry`. Loaded once and cached."""
    try:
        raw = json.loads(_TEMPLATES_INDEX.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return {entry["id"]: entry for entry in raw.get("templates", [])}


class TemplateResponse(BaseModel):
    doc_id: str
    title: str
    standard_terms: str
    cover_page: str | None = None
    # Cover-page field manifest (templates/manifests/<doc_id>.json), or
    # None for docs that still use free-form field collection.
    manifest: dict | None = None


@router.get("/{doc_id}", response_model=TemplateResponse)
def get_template(doc_id: str) -> TemplateResponse:
    entry = _index().get(doc_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown document id: {doc_id}",
        )

    standard_terms = ""
    cover_page: str | None = None
    for file_entry in entry.get("files", []):
        rel_path = file_entry.get("path")
        file_type = file_entry.get("type")
        if not rel_path:
            continue
        try:
            content = (_TEMPLATES_DIR / rel_path).read_text()
        except FileNotFoundError:
            # The index lists a file that's missing from disk — skip it
            # rather than 500. Still serves whatever else we have.
            continue
        if file_type == "standard_terms":
            standard_terms = content
        elif file_type == "cover_page":
            cover_page = content

    if not standard_terms:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"template files missing for {doc_id}",
        )

    return TemplateResponse(
        doc_id=doc_id,
        title=entry["title"],
        standard_terms=standard_terms,
        cover_page=cover_page,
        manifest=load_manifest(doc_id),
    )
