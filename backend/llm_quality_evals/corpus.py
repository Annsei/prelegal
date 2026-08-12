"""Versioned corpus loading and fail-closed validation for PL-24B."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.manifests import load_manifest

_CORPUS_PATH = Path(__file__).with_name("corpus.json")
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CATALOG_PATH = _REPO_ROOT / "catalog.json"
_MANIFESTS_DIR = _REPO_ROOT / "templates" / "manifests"
_CATEGORIES = {
    "catalog_routing",
    "manifest_field_extraction",
    "follow_up",
    "prompt_injection",
}
_EXPECTATION_KEYS = {
    "assistant_contains_cjk",
    "done",
    "expected_field_updates",
    "field_keys_manifest_only",
    "forbid_secret_patterns",
    "forbidden_field_keys",
    "forbidden_substrings",
    "requires_question",
    "selected_doc_ids",
    "selected_doc_must_exist",
}
_STATE_FIXTURES = {"empty", "required_complete"}
_BOOLEAN_EXPECTATIONS = {
    "assistant_contains_cjk",
    "done",
    "field_keys_manifest_only",
    "forbid_secret_patterns",
    "requires_question",
    "selected_doc_must_exist",
}


class CorpusValidationError(ValueError):
    def __init__(self, kind: str, message: str):
        self.kind = kind
        super().__init__(f"{kind}: {message}")


@dataclass(frozen=True)
class LiveEvalCase:
    id: str
    category: str
    doc_id: str
    target_doc_id: str
    smoke: bool
    messages: tuple[dict[str, str], ...]
    state_fixture: str
    document_state: dict[str, Any] | None
    expectations: dict[str, Any]


@dataclass(frozen=True)
class LiveEvalCorpus:
    schema_version: int
    corpus_version: str
    cases: tuple[LiveEvalCase, ...]


@dataclass(frozen=True)
class ValidatedLiveEvalCorpus:
    corpus: LiveEvalCorpus
    catalog_doc_ids: frozenset[str]
    manifest_doc_ids: frozenset[str]

    @property
    def cases(self) -> tuple[LiveEvalCase, ...]:
        return self.corpus.cases

    @property
    def smoke_cases(self) -> tuple[LiveEvalCase, ...]:
        return tuple(case for case in self.cases if case.smoke)

    @property
    def document_ids(self) -> set[str]:
        return {case.doc_id for case in self.cases if case.doc_id}

    @property
    def categories(self) -> set[str]:
        return {case.category for case in self.cases}


def load_corpus(path: Path = _CORPUS_PATH) -> LiveEvalCorpus:
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusValidationError("corpus_load_failed", type(exc).__name__) from exc
    return parse_corpus(raw)


def parse_corpus(raw: Any) -> LiveEvalCorpus:
    if not isinstance(raw, dict):
        raise CorpusValidationError("invalid_corpus", "root must be an object")
    if raw.get("schema_version") != 1:
        raise CorpusValidationError(
            "unsupported_corpus_schema", "schema_version must be 1"
        )
    version = raw.get("corpus_version")
    cases_raw = raw.get("cases")
    if not _nonempty(version) or not isinstance(cases_raw, list) or not cases_raw:
        raise CorpusValidationError(
            "invalid_corpus", "corpus_version and a non-empty cases array are required"
        )

    cases: list[LiveEvalCase] = []
    for raw_case in cases_raw:
        if not isinstance(raw_case, dict):
            raise CorpusValidationError("invalid_case", "each case must be an object")
        messages = raw_case.get("messages")
        expectations = raw_case.get("expectations")
        if not isinstance(messages, list) or not messages:
            raise CorpusValidationError("invalid_case", "messages must be non-empty")
        if not isinstance(expectations, dict):
            raise CorpusValidationError(
                "invalid_case", "expectations must be an object"
            )
        parsed_messages: list[dict[str, str]] = []
        for message in messages:
            if (
                not isinstance(message, dict)
                or message.get("role") not in {"user", "assistant"}
                or not _nonempty(message.get("content"))
            ):
                raise CorpusValidationError(
                    "invalid_case", "messages require user/assistant role and content"
                )
            parsed_messages.append(
                {"role": message["role"], "content": message["content"]}
            )
        cases.append(
            LiveEvalCase(
                id=raw_case.get("id", ""),
                category=raw_case.get("category", ""),
                doc_id=raw_case.get("doc_id", ""),
                target_doc_id=raw_case.get("target_doc_id", ""),
                smoke=raw_case.get("smoke") is True,
                messages=tuple(parsed_messages),
                state_fixture=raw_case.get("state_fixture", "empty"),
                document_state=raw_case.get("document_state"),
                expectations=expectations,
            )
        )
    return LiveEvalCorpus(
        schema_version=1,
        corpus_version=version,
        cases=tuple(cases),
    )


def validate_corpus(
    corpus: LiveEvalCorpus,
    *,
    catalog_doc_ids: set[str] | None = None,
    manifest_doc_ids: set[str] | None = None,
    require_all_documents: bool = True,
    require_all_categories: bool = True,
    require_three_smoke_cases: bool = True,
) -> ValidatedLiveEvalCorpus:
    catalog_ids = catalog_doc_ids or _load_catalog_doc_ids()
    manifest_ids = manifest_doc_ids or {
        path.stem for path in _MANIFESTS_DIR.glob("*.json")
    }
    if catalog_ids != manifest_ids:
        raise CorpusValidationError(
            "catalog_manifest_mismatch",
            f"catalog={sorted(catalog_ids)} manifest={sorted(manifest_ids)}",
        )

    case_ids = [case.id for case in corpus.cases]
    if any(not _nonempty(case_id) for case_id in case_ids):
        raise CorpusValidationError("invalid_case_id", "case ids must be non-empty")
    if len(case_ids) != len(set(case_ids)):
        raise CorpusValidationError("duplicate_case_id", "case ids must be unique")

    for case in corpus.cases:
        if case.category not in _CATEGORIES:
            raise CorpusValidationError(
                "unknown_category", f"{case.id}: {case.category}"
            )
        if case.doc_id not in catalog_ids:
            raise CorpusValidationError(
                "unknown_document_id", f"{case.id}: {case.doc_id}"
            )
        if case.target_doc_id not in catalog_ids:
            raise CorpusValidationError(
                "unknown_target_document_id", f"{case.id}: {case.target_doc_id}"
            )
        if case.state_fixture not in _STATE_FIXTURES:
            raise CorpusValidationError(
                "unknown_state_fixture", f"{case.id}: {case.state_fixture}"
            )
        if case.document_state is not None and not isinstance(
            case.document_state, dict
        ):
            raise CorpusValidationError(
                "invalid_document_state", f"{case.id}: document_state must be object"
            )
        unknown_expectations = set(case.expectations) - _EXPECTATION_KEYS
        if unknown_expectations:
            raise CorpusValidationError(
                "invalid_expectation_key",
                f"{case.id}: {sorted(unknown_expectations)}",
            )
        for key in _BOOLEAN_EXPECTATIONS:
            value = case.expectations.get(key)
            if key in case.expectations and type(value) is not bool:
                raise CorpusValidationError(
                    "invalid_expectation_value", f"{case.id}: {key}"
                )
        selected = case.expectations.get("selected_doc_ids")
        if selected is not None and (
            type(selected) is not list
            or not selected
            or any(type(item) is not str for item in selected)
            or (
                selected != [""]
                and any(
                    not _nonempty(item) or item not in catalog_ids
                    for item in selected
                )
            )
        ):
            raise CorpusValidationError(
                "invalid_expectation_value", f"{case.id}: selected_doc_ids"
            )
        for key in ("forbidden_field_keys", "forbidden_substrings"):
            value = case.expectations.get(key)
            if value is not None and (
                type(value) is not list
                or not value
                or any(not _nonempty(item) for item in value)
            ):
                raise CorpusValidationError(
                    "invalid_expectation_value", f"{case.id}: {key}"
                )
        expected_fields = case.expectations.get("expected_field_updates")
        if expected_fields is not None and (
            type(expected_fields) is not dict
            or not expected_fields
            or any(
                not _nonempty(key) or not _nonempty(value)
                for key, value in expected_fields.items()
            )
        ):
            raise CorpusValidationError(
                "invalid_expectation_value", f"{case.id}: expected_field_updates"
            )
        manifest = load_manifest(case.doc_id)
        if manifest is None:
            raise CorpusValidationError(
                "manifest_unavailable", f"{case.id}: {case.doc_id}"
            )
        if expected_fields is not None:
            manifest_keys = {
                field.get("key")
                for field in manifest.get("fields", [])
                if _nonempty(field.get("key"))
            }
            if not set(expected_fields) <= manifest_keys:
                raise CorpusValidationError(
                    "invalid_expectation_value",
                    f"{case.id}: expected_field_updates keys",
                )

    validated = ValidatedLiveEvalCorpus(
        corpus=corpus,
        catalog_doc_ids=frozenset(catalog_ids),
        manifest_doc_ids=frozenset(manifest_ids),
    )
    if require_all_documents and validated.document_ids != catalog_ids:
        raise CorpusValidationError(
            "document_coverage_incomplete",
            f"covered={sorted(validated.document_ids)} expected={sorted(catalog_ids)}",
        )
    if require_all_categories and validated.categories != _CATEGORIES:
        raise CorpusValidationError(
            "category_coverage_incomplete",
            f"covered={sorted(validated.categories)} expected={sorted(_CATEGORIES)}",
        )
    if require_three_smoke_cases and len(validated.smoke_cases) != 3:
        raise CorpusValidationError(
            "smoke_case_count_mismatch", "exactly three smoke cases are required"
        )
    return validated


def _load_catalog_doc_ids() -> set[str]:
    raw = json.loads(_CATALOG_PATH.read_text())
    return {
        item["id"]
        for item in raw.get("documents", [])
        if isinstance(item, dict)
        and item.get("status") == "available"
        and _nonempty(item.get("id"))
    }


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
