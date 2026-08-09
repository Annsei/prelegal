"""Loading and structural validation for the deterministic corpus."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.manifests import load_manifest, manifest_field_keys

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_ROOT.parent
_CORPUS_PATH = Path(__file__).with_name("corpus.json")
_CATALOG_PATH = _REPO_ROOT / "catalog.json"
_MANIFESTS_DIR = _REPO_ROOT / "templates" / "manifests"
_RENDERERS = {"docx", "pdf"}
_REQUIRED_CASE_KINDS = {
    "complete_state",
    "missing_required",
    "required_when",
    "field_constraints",
    "unknown_field",
    "conflict_transitions",
    "idempotency_concurrency",
    "public_put_protection",
    "invalid_downloads",
    "cross_format_semantics",
}


class CorpusValidationError(ValueError):
    def __init__(self, kind: str, message: str):
        self.kind = kind
        super().__init__(message)


@dataclass(frozen=True)
class CorpusCase:
    id: str
    kind: str


@dataclass(frozen=True)
class CorpusDocument:
    doc_id: str
    anchor_field: str


@dataclass(frozen=True)
class ContractQualityCorpus:
    schema_version: int
    renderers: tuple[str, ...]
    cases: tuple[CorpusCase, ...]
    documents: tuple[CorpusDocument, ...]
    raw: dict[str, Any]

    @property
    def doc_ids(self) -> set[str]:
        return {document.doc_id for document in self.documents}


@dataclass(frozen=True)
class ValidatedCorpus:
    corpus: ContractQualityCorpus
    catalog_doc_ids: set[str]
    manifest_doc_ids: set[str]
    corpus_doc_ids: set[str]

    @property
    def documents(self) -> tuple[CorpusDocument, ...]:
        return self.corpus.documents


def load_corpus(path: Path = _CORPUS_PATH) -> ContractQualityCorpus:
    return _parse_corpus(json.loads(path.read_text()))


def validate_corpus(
    corpus: ContractQualityCorpus | dict[str, Any],
    *,
    catalog_doc_ids: set[str] | None = None,
    manifest_doc_ids: set[str] | None = None,
) -> ValidatedCorpus:
    parsed = (
        corpus
        if isinstance(corpus, ContractQualityCorpus)
        else _parse_corpus(corpus)
    )
    catalog_ids = catalog_doc_ids or _load_catalog_doc_ids()
    manifest_ids = manifest_doc_ids or {
        path.stem for path in _MANIFESTS_DIR.glob("*.json")
    }

    if set(parsed.renderers) != _RENDERERS:
        raise CorpusValidationError(
            "renderer_coverage_missing",
            "The quality corpus must exercise both docx and pdf renderers.",
        )

    case_ids = [case.id for case in parsed.cases]
    if len(case_ids) != len(set(case_ids)):
        raise CorpusValidationError(
            "duplicate_case_id",
            "Quality corpus case ids must be unique.",
        )
    case_kinds = [case.kind for case in parsed.cases]
    if len(case_kinds) != len(set(case_kinds)):
        raise CorpusValidationError(
            "duplicate_case_kind",
            "Quality corpus case kinds must be unique.",
        )
    if set(case_kinds) != _REQUIRED_CASE_KINDS:
        raise CorpusValidationError(
            "case_coverage_mismatch",
            _set_difference_message(
                "required_case",
                _REQUIRED_CASE_KINDS,
                "corpus_case",
                set(case_kinds),
            ),
        )

    document_ids = [document.doc_id for document in parsed.documents]
    if len(document_ids) != len(set(document_ids)):
        raise CorpusValidationError(
            "duplicate_document_id",
            "Quality corpus document ids must be unique.",
        )
    corpus_ids = set(document_ids)

    if catalog_ids != manifest_ids:
        raise CorpusValidationError(
            "catalog_manifest_mismatch",
            _set_difference_message("catalog", catalog_ids, "manifest", manifest_ids),
        )
    if catalog_ids != corpus_ids:
        raise CorpusValidationError(
            "catalog_corpus_mismatch",
            _set_difference_message("catalog", catalog_ids, "corpus", corpus_ids),
        )

    for document in parsed.documents:
        manifest = load_manifest(document.doc_id)
        if manifest is None:
            raise CorpusValidationError(
                "manifest_unavailable",
                f"Manifest could not be loaded for {document.doc_id}.",
            )
        keys = set(manifest_field_keys(manifest))
        if document.anchor_field not in keys:
            raise CorpusValidationError(
                "unknown_corpus_field",
                f"{document.doc_id} corpus anchor does not exist: "
                f"{document.anchor_field}",
            )
        _validate_manifest_conditions(document.doc_id, manifest, keys)

    return ValidatedCorpus(
        corpus=parsed,
        catalog_doc_ids=catalog_ids,
        manifest_doc_ids=manifest_ids,
        corpus_doc_ids=corpus_ids,
    )


def _parse_corpus(raw: dict[str, Any]) -> ContractQualityCorpus:
    if raw.get("schema_version") != 1:
        raise CorpusValidationError(
            "unsupported_corpus_schema",
            "Only contract quality corpus schema version 1 is supported.",
        )
    try:
        cases = tuple(
            CorpusCase(id=item["id"], kind=item["kind"])
            for item in raw["cases"]
        )
        documents = tuple(
            CorpusDocument(
                doc_id=item["doc_id"],
                anchor_field=item["anchor_field"],
            )
            for item in raw["documents"]
        )
        renderers = tuple(raw["renderers"])
    except (KeyError, TypeError) as exc:
        raise CorpusValidationError(
            "invalid_corpus",
            "Quality corpus is missing a required property.",
        ) from exc
    return ContractQualityCorpus(
        schema_version=1,
        renderers=renderers,
        cases=cases,
        documents=documents,
        raw=raw,
    )


def _load_catalog_doc_ids() -> set[str]:
    raw = json.loads(_CATALOG_PATH.read_text())
    return {
        entry["id"]
        for entry in raw.get("documents", [])
        if isinstance(entry, dict)
        and isinstance(entry.get("id"), str)
        and entry.get("status") == "available"
    }


def _validate_manifest_conditions(
    doc_id: str,
    manifest: dict[str, Any],
    field_keys: set[str],
) -> None:
    for field in manifest.get("fields", []):
        if not isinstance(field, dict):
            continue
        raw = field.get("required_when")
        conditions = raw if isinstance(raw, list) else [raw]
        for condition in conditions:
            if condition is None:
                continue
            key = condition.get("field") if isinstance(condition, dict) else None
            if key not in field_keys:
                raise CorpusValidationError(
                    "unknown_condition_field",
                    f"{doc_id}:{field.get('key')} references unknown field {key}.",
                )


def _set_difference_message(
    left_name: str,
    left: set[str],
    right_name: str,
    right: set[str],
) -> str:
    return (
        f"{left_name}/{right_name} document sets differ; "
        f"only_{left_name}={sorted(left - right)}, "
        f"only_{right_name}={sorted(right - left)}"
    )
