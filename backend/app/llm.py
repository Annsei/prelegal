"""LLM client for the chat feature.

Routes chat completions through LiteLLM → OpenRouter → Cerebras as required
by CLAUDE.md. Structured Outputs are used to extract document field proposals
reliably; the LLM returns one JSON object containing both the natural-language
reply and any new field values it learned this turn.

The chat is multi-document aware (PL-6): it knows the catalog of supported
documents and can recommend the closest match when a user asks for
something we don't offer. It collects key terms for any catalog document;
manifest-backed documents constrain those terms to their declared fields.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import litellm

from app.manifests import load_manifest, manifest_field_keys

MODEL = "openrouter/openai/gpt-oss-120b"

# Force Cerebras as the inference provider so we don't silently fall back
# to a slower one and lose response-time consistency. See the project's
# .claude/skills/cerebras/SKILL.md for the rationale.
PROVIDER_ROUTING = {"order": ["cerebras"], "allow_fallbacks": False}

# catalog.json lives at the repo root. From this file, that's three
# parents up: backend/app/llm.py → backend/app → backend → repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CATALOG_PATH = _REPO_ROOT / "catalog.json"


def _load_catalog() -> str:
    """Load catalog.json as a compact JSON string for prompt injection.

    Loaded once at import time. If the file is missing (developer ran from
    a stripped checkout), fall back to an empty catalog rather than crashing
    the whole module — the assistant will just be less helpful about doc
    routing, but auth/health endpoints still work.
    """
    try:
        return json.dumps(json.loads(_CATALOG_PATH.read_text()), ensure_ascii=False)
    except (FileNotFoundError, json.JSONDecodeError):
        return json.dumps({"documents": []}, ensure_ascii=False)


CATALOG_JSON = _load_catalog()


SYSTEM_PROMPT = f"""\
You are a friendly legal-drafting assistant for Prelegal, helping users draft \
PRC-law (中华人民共和国法律) Chinese legal agreements from Prelegal's \
standard templates.

## Supported documents

The catalog below lists every document type we offer. **Entries marked \
`status: "available"` support full drafting and PDF download.** Entries \
marked `status: "planned"` have their underlying templates loaded and \
visible in the preview pane, and you can still collect the key terms for \
them via chat — the user just can't yet download a finished PDF for those. \
For requests **outside** the catalog (e.g. employment contracts, leases, \
terms of service), explain that we can't generate that document and \
recommend the closest available item from the catalog.

Catalog (JSON):
{CATALOG_JSON}

## Picking a document

The very first thing you must do in any new conversation is figure out \
which document the user wants and set `selected_doc_id` to the matching \
catalog id (e.g. "mutual-nda", "cloud-service-agreement"). If the user's \
intent is ambiguous, ask a clarifying question and leave `selected_doc_id` \
empty until they answer. Once set, **keep `selected_doc_id` populated on \
every subsequent turn** so the frontend can keep the preview pane in sync.

If the user later changes their mind ("actually let's do an SLA instead"), \
update `selected_doc_id` to the new id.

## Collecting field values

Use `field_updates` to record cover-page-level data: party names, dates, \
governing law, key commercial terms, etc. For manifest-backed documents, \
use the exact keys from the field checklist. For documents without a \
manifest, choose concise human-readable keys matching the underlying \
template labels.

Only include keys the user has *just* told you about — never repeat values \
already present in the current state. Always reply in the same language the \
user used. The legal templates are Simplified-Chinese PRC-law documents — \
keep field values in Simplified Chinese (company names as registered, \
dates in ISO YYYY-MM-DD; amounts and periods written in Chinese, e.g. \
"人民币 20,000 元/月", "12 个月").

## Conversation rules

- Whenever `done` is false, your `assistant_message` MUST end with a \
question (terminated by "?" or "？"). The user should always see what to \
answer next — never leave the conversation hanging on a statement.
- When a "Field checklist" section appears below, the selected document \
supports full cover-page drafting: collect those fields and set \
`done: true` once every required one has a value (from this conversation \
or the current state).
- For any other document, keep `done: false` (we don't yet emit a final \
PDF for those). Tell the user the preview shows the underlying template \
and you'll keep collecting key terms.
"""


def _manifest_prompt_section(manifest: dict[str, Any]) -> str:
    """Render a manifest as a prompt section: the exact field_updates keys
    to use for the selected document, with hints and examples."""
    lines = [
        "## Field checklist for the selected document",
        "",
        f"The user's current document is **{manifest.get('doc_id', '')}**. "
        "Collect values for the cover-page fields below, using EXACTLY "
        "these keys in `field_updates` — never invent other keys for this "
        "document. Ask about them conversationally (group related ones); "
        "don't interrogate one field at a time.",
        "",
    ]
    for field in manifest.get("fields", []):
        key = field.get("key", "")
        requirement = "required" if field.get("required") else "optional"
        hint = (field.get("hint") or {}).get("en", "")
        example = field.get("example", "")
        parts = [f'- "{key}" ({requirement})']
        if hint:
            parts.append(f": {hint}")
        if example:
            parts.append(f' — e.g. "{example}"')
        lines.append("".join(parts))
    lines.append("")
    lines.append(
        "When every required field has a value, set `done: true` and tell "
        "the user the cover page is complete — they can review the "
        "preview and download the PDF."
    )
    return "\n".join(lines)


# The structured-output schema. `field_updates` is intentionally partial:
# the LLM should only fill keys it actually extracted this turn.
CHAT_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "assistant_message": {
            "type": "string",
            "description": "Natural-language reply to show the user.",
        },
        "selected_doc_id": {
            "type": "string",
            "description": (
                "Catalog id of the document the user is drafting. Empty "
                "string until intent is clear."
            ),
        },
        "field_updates": {
            "type": "object",
            "description": (
                "Key/value updates for the selected document. Manifest "
                "documents constrain keys to the field checklist."
            ),
            "additionalProperties": {"type": "string"},
        },
        "done": {
            "type": "boolean",
            "description": (
                "True when the selected manifest document has all required "
                "field values."
            ),
        },
    },
    "required": ["assistant_message", "done"],
    "additionalProperties": False,
}


def _schema_for(manifest: dict[str, Any] | None) -> dict[str, Any]:
    """Response schema, with field_updates constrained to the manifest's
    keys when the selected document has one. Free-form otherwise."""
    if not manifest:
        return CHAT_RESPONSE_SCHEMA
    schema = json.loads(json.dumps(CHAT_RESPONSE_SCHEMA))  # deep copy
    schema["properties"]["field_updates"] = {
        "type": "object",
        "description": (
            "Values for the selected document's cover-page fields. Keys "
            "MUST come from the field checklist."
        ),
        "properties": {
            key: {"type": "string"} for key in manifest_field_keys(manifest)
        },
        "additionalProperties": False,
    }
    return schema


class LLMUnavailableError(RuntimeError):
    """Raised when OPENROUTER_API_KEY is missing or the call fails."""


def _ensure_api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise LLMUnavailableError(
            "OPENROUTER_API_KEY is not set. Configure it in the environment "
            "before calling the chat endpoint.",
        )
    return key


_QUESTION_MARKS = ("?", "？")
_LITERAL_NEWLINE_TOKEN = re.compile(r"\\r\\n|\\n")
_PATHISH_PRECEDING_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_:/\\.-",
)
_FORMAT_NEWLINE_PRECEDING_CHARS = frozenset(
    " \t([{<\"'“‘《（【「『。！？!?；;，,、）)]】」』”’",
)


def _ends_with_question(text: str) -> bool:
    stripped = text.rstrip()
    return bool(stripped) and stripped[-1] in _QUESTION_MARKS


def _is_chinese(text: str) -> bool:
    # CJK Unified Ideographs (一-鿿) covers ~all conversational
    # Mandarin; Extension A (㐀-䶿) handles less-common characters
    # the LLM may emit. Punctuation alone wouldn't trigger this, but real
    # replies always include at least one ideograph.
    return any(
        "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿" for ch in text
    )


def _normalize_assistant_message(message: str) -> str:
    """Decode only LLM formatting newline escapes in assistant copy.

    Some upstream responses double-escape paragraph breaks as literal
    ``\\n``/``\\r\\n`` inside the JSON string. Avoid a generic unicode_escape
    pass: assistant text may legitimately mention backslash sequences such
    as Windows paths (for example ``C:\\name``), and field values are handled
    separately by `_normalize_result`.
    """

    pieces: list[str] = []
    cursor = 0
    previous_was_converted = False
    for match in _LITERAL_NEWLINE_TOKEN.finditer(message):
        token = match.group(0)
        pieces.append(message[cursor : match.start()])
        if _should_decode_literal_newline(
            message,
            start=match.start(),
            end=match.end(),
            previous_was_converted=previous_was_converted,
        ):
            pieces.append("\n")
            previous_was_converted = True
        else:
            pieces.append(token)
            previous_was_converted = False
        cursor = match.end()
    pieces.append(message[cursor:])
    return "".join(pieces)


def _should_decode_literal_newline(
    message: str,
    *,
    start: int,
    end: int,
    previous_was_converted: bool,
) -> bool:
    if previous_was_converted:
        return True
    if _LITERAL_NEWLINE_TOKEN.match(message, end):
        return True
    before = message[start - 1] if start > 0 else ""
    if not before:
        return True
    if before in _FORMAT_NEWLINE_PRECEDING_CHARS:
        return True
    if _is_chinese(before):
        return True
    return before not in _PATHISH_PRECEDING_CHARS and before.isspace()


def _ensure_followup(message: str) -> str:
    """Append a localized follow-up question if the message doesn't end with one.

    Last-resort fallback after the LLM and one retry both failed to comply
    with the "always end with a question" rule. The fallback is intentionally
    generic so it makes sense regardless of context.
    """
    if _ends_with_question(message):
        return message
    fallback = (
        "请问您还有什么需要补充的吗？"
        if _is_chinese(message)
        else "Anything else you'd like to share?"
    )
    return f"{message.rstrip()} {fallback}"


def _classify_llm_error(exc: BaseException) -> str:
    """Map a raw litellm/OpenRouter exception to a short, user-facing message.

    Goal: don't dump the entire stringified exception (which can be a
    multi-kilobyte HTML or JSON blob) into the chat panel. Instead, show
    one sentence the user can act on.
    """
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "ratelimit" in name or "429" in text or "rate-limited" in text:
        return (
            "AI service is rate-limited upstream right now. "
            "Please retry in a moment."
        )
    if "authentication" in name or "401" in text or "invalid api key" in text:
        return "AI service rejected the API key. Check OPENROUTER_API_KEY."
    if "timeout" in name or "timed out" in text:
        return "AI service timed out. Please retry."
    if "403" in text or "blocked" in text:
        return (
            "AI provider blocked the request (network or region issue). "
            "Please retry shortly."
        )
    # Fallback: still surface something short rather than the full trace.
    return "AI service is unavailable right now. Please retry shortly."


def _call_llm(
    messages: list[dict[str, str]],
    system: str,
    api_key: str,
    schema: dict[str, Any],
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        response = litellm.completion(
            model=MODEL,
            api_key=api_key,
            messages=[{"role": "system", "content": system}, *messages],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "document_chat_turn",
                    "schema": schema,
                    # Don't request strict mode: field_updates is
                    # intentionally partial — only the keys the model just
                    # learned should appear.
                },
            },
            extra_body={"provider": PROVIDER_ROUTING},
            temperature=0.3,
        )
    except Exception as exc:  # litellm wraps many transport errors
        raise LLMUnavailableError(_classify_llm_error(exc)) from exc

    try:
        content = response.choices[0].message.content
        parsed = json.loads(content)
    except (AttributeError, IndexError, json.JSONDecodeError, TypeError) as exc:
        raise LLMUnavailableError(
            f"LLM returned an unparseable response: {exc}",
        ) from exc
    return _normalize_result(parsed, manifest)


def _normalize_result(
    data: Any,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Coerce parsed LLM JSON into the exact shape the route layer expects.

    Structured Outputs run without strict mode (see the response_format
    comment above), so the model can omit keys or return wrong scalar types
    (e.g. a bare number for a field value). Anything unrecoverable becomes an
    LLMUnavailableError so it surfaces as a classified 502, never a raw 500.
    """
    if not isinstance(data, dict):
        raise LLMUnavailableError(
            "LLM returned an unparseable response: not a JSON object",
        )
    message = data.get("assistant_message")
    if not isinstance(message, str) or not message.strip():
        raise LLMUnavailableError(
            "AI service returned an incomplete reply. Please retry.",
        )
    doc_id = data.get("selected_doc_id")
    raw_fields = data.get("field_updates")
    field_updates: dict[str, str] = {}
    allowed_fields = set(manifest_field_keys(manifest)) if manifest else None
    if isinstance(raw_fields, dict):
        for key, value in raw_fields.items():
            field_key = str(key)
            # Structured outputs are intentionally non-strict for partial
            # MNDA updates, so manifest enforcement happens again here.
            if allowed_fields is not None and field_key not in allowed_fields:
                continue
            field_updates[field_key] = (
                value if isinstance(value, str)
                else json.dumps(value, ensure_ascii=False)
            )
    return {
        "assistant_message": _normalize_assistant_message(message),
        "selected_doc_id": doc_id if isinstance(doc_id, str) else "",
        # Compatibility for the route/frontend response shape while the
        # typed MNDA channel is retired.
        "mnda_updates": {},
        "field_updates": field_updates,
        "done": bool(data.get("done", False)),
    }


def chat_complete(
    messages: list[dict[str, str]],
    mnda_state: dict[str, Any],
    doc_id: str = "",
    document_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call the LLM and return the parsed structured response.

    `doc_id` is the document the frontend currently has open. When that
    document has a cover-page manifest, its field checklist is injected
    into the system prompt and the structured-output schema constrains
    `field_updates` to exactly those keys. (The manifest kicks in from
    the turn after the LLM picks the doc — the exchange stays stateless,
    so the frontend echoes the selection back on subsequent turns.)

    Enforces the "always ask a follow-up" contract: when `done` is false but
    the message doesn't end with a question, retry once with a corrective
    nudge. If the retry still fails, append a localized fallback question so
    the user always has something to answer.

    Raises LLMUnavailableError on auth/transport/parse failures so the
    route layer can surface a 502 with a stable shape.
    """
    api_key = _ensure_api_key()

    manifest = load_manifest(doc_id)
    schema = _schema_for(manifest)
    system = SYSTEM_PROMPT
    if manifest:
        system += "\n\n" + _manifest_prompt_section(manifest)

    # `mnda_state` remains accepted by the public API for older clients, but
    # the retired typed MNDA object is no longer authoritative and should not
    # be reintroduced into the LLM's grounding context.
    current_state: dict[str, Any] = {"doc_id": doc_id, "fields": {}}
    if isinstance(document_state, dict):
        current_state.update(document_state)
    current_state.pop("mnda", None)

    state_summary = json.dumps(current_state, indent=2, ensure_ascii=False)
    system += f"\n\nCurrent document state:\n{state_summary}"

    result = _call_llm(messages, system, api_key, schema, manifest)

    needs_followup = (
        not result.get("done")
        and not _ends_with_question(result.get("assistant_message", ""))
    )
    if needs_followup:
        # Preserve any field values the first call already extracted — the
        # retry is purely about phrasing the reply, not re-discovering data.
        # Without this merge, a user message like "Acme is party 1" would
        # populate party1 on the first call and lose it on the retry.
        first_fields = result.get("field_updates") or {}
        first_doc_id = result.get("selected_doc_id") or ""
        retry_system = (
            system
            + "\n\nIMPORTANT: Your previous reply did not end with a question. "
            "While `done` is false, `assistant_message` MUST end with a question."
        )
        result = _call_llm(messages, retry_system, api_key, schema, manifest)
        result["field_updates"] = {
            **first_fields,
            **(result.get("field_updates") or {}),
        }
        # Don't let the retry blank out a doc id the first call established.
        if not result.get("selected_doc_id") and first_doc_id:
            result["selected_doc_id"] = first_doc_id
        still_missing = (
            not result.get("done")
            and not _ends_with_question(result.get("assistant_message", ""))
        )
        if still_missing:
            result["assistant_message"] = _ensure_followup(
                result.get("assistant_message") or "",
            )

    return result
