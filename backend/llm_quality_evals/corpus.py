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
    "field_updates_expectation",
    "field_keys_manifest_only",
    "forbid_secret_patterns",
    "forbidden_field_keys",
    "forbidden_substrings",
    "requires_question",
    "selected_doc_ids",
    "selected_doc_must_exist",
}
_FIELD_UPDATE_MODES = {"exact", "contains", "empty"}
_STABLE_SMOKE_CASE_IDS = {
    "routing.mutual-nda",
    "routing.cloud-service-agreement",
    "routing.data-processing-agreement",
}
_ROUTING_REQUIRED_EXPECTATIONS = {
    "selected_doc_ids",
    "done",
    "requires_question",
    "assistant_contains_cjk",
    "field_keys_manifest_only",
    "forbid_secret_patterns",
}
_FOLLOW_UP_REQUIRED_EXPECTATIONS = {
    "selected_doc_ids",
    "done",
    "requires_question",
    "assistant_contains_cjk",
    "field_keys_manifest_only",
    "field_updates_expectation",
}
_MANIFEST_EXTRACTION_REQUIRED_EXPECTATIONS = {
    "selected_doc_ids",
    "selected_doc_must_exist",
    "field_keys_manifest_only",
    "field_updates_expectation",
    "done",
    "assistant_contains_cjk",
    "forbid_secret_patterns",
}
_PROMPT_INJECTION_REQUIRED_EXPECTATIONS = {
    "selected_doc_ids",
    "selected_doc_must_exist",
    "done",
    "requires_question",
    "assistant_contains_cjk",
    "field_keys_manifest_only",
    "forbid_secret_patterns",
    "field_updates_expectation",
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
    schema_version = raw.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
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
        smoke = raw_case.get("smoke")
        if type(smoke) is not bool:
            raise CorpusValidationError(
                "invalid_smoke_flag",
                f"{raw_case.get('id', '<unknown>')}: smoke must be a boolean",
            )
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
                smoke=smoke,
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
        manifest = load_manifest(case.doc_id)
        if manifest is None:
            raise CorpusValidationError(
                "manifest_unavailable", f"{case.id}: {case.doc_id}"
            )
        manifest_keys = {
            field.get("key")
            for field in manifest.get("fields", [])
            if _nonempty(field.get("key"))
        }
        _validate_field_update_expectation(case, manifest_keys)
        _validate_category_contract(case)

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
    if require_three_smoke_cases:
        smoke_ids = {case.id for case in validated.smoke_cases}
        if smoke_ids != _STABLE_SMOKE_CASE_IDS:
            raise CorpusValidationError(
                "smoke_case_set_mismatch",
                f"actual={sorted(smoke_ids)} expected={sorted(_STABLE_SMOKE_CASE_IDS)}",
            )
    return validated


def _validate_field_update_expectation(
    case: LiveEvalCase, manifest_keys: set[str]
) -> None:
    expectation = case.expectations.get("field_updates_expectation")
    if expectation is None:
        return
    if type(expectation) is not dict or set(expectation) - {"mode", "values"}:
        raise CorpusValidationError(
            "invalid_field_update_expectation", f"{case.id}: invalid object"
        )
    mode = expectation.get("mode")
    values = expectation.get("values")
    if mode not in _FIELD_UPDATE_MODES:
        raise CorpusValidationError(
            "invalid_field_update_expectation", f"{case.id}: invalid mode"
        )
    if mode == "empty":
        if values not in (None, {}):
            raise CorpusValidationError(
                "invalid_field_update_expectation",
                f"{case.id}: empty mode cannot contain values",
            )
        return
    if type(values) is not dict or not values or any(
        type(key) is not str
        or type(value) is not str
        or not key.strip()
        or not value.strip()
        for key, value in values.items()
    ):
        raise CorpusValidationError(
            "invalid_field_update_expectation", f"{case.id}: invalid values"
        )
    if not set(values) <= manifest_keys:
        raise CorpusValidationError(
            "invalid_field_update_expectation", f"{case.id}: unknown manifest key"
        )


def _validate_category_contract(case: LiveEvalCase) -> None:
    expectations = case.expectations
    if case.category == "catalog_routing":
        _require_expectations(case, _ROUTING_REQUIRED_EXPECTATIONS)
        if expectations["selected_doc_ids"] != [case.target_doc_id]:
            raise CorpusValidationError(
                "routing_target_mismatch", f"{case.id}: target must be exact"
            )
        _require_boolean_values(
            case,
            {
                "done": False,
                "requires_question": True,
                "assistant_contains_cjk": True,
                "field_keys_manifest_only": True,
                "forbid_secret_patterns": True,
            },
        )
        return
    if case.category == "manifest_field_extraction":
        _require_expectations(case, _MANIFEST_EXTRACTION_REQUIRED_EXPECTATIONS)
        if expectations["selected_doc_ids"] != [case.target_doc_id]:
            raise CorpusValidationError(
                "routing_target_mismatch", f"{case.id}: target must be exact"
            )
        _require_boolean_values(
            case,
            {
                "selected_doc_must_exist": True,
                "field_keys_manifest_only": True,
                "assistant_contains_cjk": True,
                "forbid_secret_patterns": True,
            },
        )
        if expectations["done"] is False:
            _require_expectations(case, {"requires_question"})
            _require_boolean_values(case, {"requires_question": True})
        elif "requires_question" in expectations:
            _require_boolean_values(case, {"requires_question": False})
        return
    if case.category == "follow_up":
        _require_expectations(case, _FOLLOW_UP_REQUIRED_EXPECTATIONS)
        _require_boolean_values(
            case,
            {
                "done": False,
                "requires_question": True,
                "assistant_contains_cjk": True,
                "field_keys_manifest_only": True,
            },
        )
        return
    _require_expectations(case, _PROMPT_INJECTION_REQUIRED_EXPECTATIONS)
    _require_boolean_values(
        case,
        {
            "selected_doc_must_exist": True,
            "done": False,
            "requires_question": True,
            "assistant_contains_cjk": True,
            "field_keys_manifest_only": True,
            "forbid_secret_patterns": True,
        },
    )
    if expectations["selected_doc_ids"] != [case.target_doc_id]:
        raise CorpusValidationError(
            "routing_target_mismatch", f"{case.id}: target must be exact"
        )
    if not ({"forbidden_substrings", "forbidden_field_keys"} & set(expectations)):
        raise CorpusValidationError(
            "injection_contract_missing_prohibition",
            f"{case.id}: scenario-specific prohibition required",
        )


def _require_expectations(case: LiveEvalCase, required: set[str]) -> None:
    missing = required - set(case.expectations)
    if missing:
        raise CorpusValidationError(
            "category_contract_missing", f"{case.id}: {sorted(missing)}"
        )


def _require_boolean_values(case: LiveEvalCase, expected: dict[str, bool]) -> None:
    mismatched = [
        key
        for key, value in expected.items()
        if case.expectations.get(key) is not value
    ]
    if mismatched:
        raise CorpusValidationError(
            "category_contract_mismatch", f"{case.id}: {sorted(mismatched)}"
        )


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
