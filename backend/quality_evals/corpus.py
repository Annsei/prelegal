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
    corpus: ContractQualityCorpus | Any,
    *,
    catalog_doc_ids: set[str] | None = None,
    manifest_doc_ids: set[str] | None = None,
    registered_case_kinds: set[str] | None = None,
) -> ValidatedCorpus:
    parsed = (
        corpus
        if isinstance(corpus, ContractQualityCorpus)
        else _parse_corpus(corpus)
    )
    catalog_ids = (
        _load_catalog_doc_ids() if catalog_doc_ids is None else catalog_doc_ids
    )
    manifest_ids = (
        {path.stem for path in _MANIFESTS_DIR.glob("*.json")}
        if manifest_doc_ids is None
        else manifest_doc_ids
    )

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
    if registered_case_kinds is not None:
        unregistered = set(case_kinds) - registered_case_kinds
        if unregistered:
            raise CorpusValidationError(
                "unregistered_case_kind",
                f"No evaluator is registered for: {sorted(unregistered)}.",
            )
        undispatched = registered_case_kinds - set(case_kinds)
        if undispatched:
            raise CorpusValidationError(
                "undispatched_case_kind",
                "Registered evaluators are absent from the corpus: "
                f"{sorted(undispatched)}.",
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
        if not any(
            _supports_distinct_values(field)
            for field in manifest.get("fields", [])
            if isinstance(field, dict)
        ):
            raise CorpusValidationError(
                "field_witness_unavailable",
                f"{document.doc_id} has no field with two valid witness values.",
            )

    return ValidatedCorpus(
        corpus=parsed,
        catalog_doc_ids=catalog_ids,
        manifest_doc_ids=manifest_ids,
        corpus_doc_ids=corpus_ids,
    )


def _parse_corpus(raw: Any) -> ContractQualityCorpus:
    if not isinstance(raw, dict):
        raise CorpusValidationError(
            "invalid_corpus",
            "Quality corpus root must be a JSON object.",
        )
    schema_version = raw.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        raise CorpusValidationError(
            "unsupported_corpus_schema",
            "Only contract quality corpus schema version 1 is supported.",
        )
    cases_raw = raw.get("cases")
    documents_raw = raw.get("documents")
    renderers_raw = raw.get("renderers")
    if not all(
        isinstance(value, list)
        for value in (cases_raw, documents_raw, renderers_raw)
    ):
        raise CorpusValidationError(
            "invalid_corpus",
            "Quality corpus cases, documents, and renderers must be arrays.",
        )

    cases: list[CorpusCase] = []
    for item in cases_raw:
        if (
            not isinstance(item, dict)
            or not _nonempty_string(item.get("id"))
            or not _nonempty_string(item.get("kind"))
        ):
            raise CorpusValidationError(
                "invalid_corpus",
                "Each quality case requires non-empty string id and kind values.",
            )
        cases.append(CorpusCase(id=item["id"], kind=item["kind"]))

    documents: list[CorpusDocument] = []
    for item in documents_raw:
        if (
            not isinstance(item, dict)
            or not _nonempty_string(item.get("doc_id"))
            or not _nonempty_string(item.get("anchor_field"))
        ):
            raise CorpusValidationError(
                "invalid_corpus",
                "Each quality document requires string doc_id and anchor_field values.",
            )
        documents.append(
            CorpusDocument(
                doc_id=item["doc_id"],
                anchor_field=item["anchor_field"],
            )
        )

    if not all(_nonempty_string(renderer) for renderer in renderers_raw):
        raise CorpusValidationError(
            "invalid_corpus",
            "Each renderer must be a non-empty string.",
        )
    return ContractQualityCorpus(
        schema_version=1,
        renderers=tuple(renderers_raw),
        cases=tuple(cases),
        documents=tuple(documents),
        raw=raw,
    )


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _supports_distinct_values(field: dict[str, Any]) -> bool:
    choices = field.get("enum") or field.get("options")
    if isinstance(choices, list) and choices:
        return len({value for value in choices if _nonempty_string(value)}) >= 2
    return field.get("type") in {"string", "text", "date"}


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
