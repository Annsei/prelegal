"""LLM client for the chat feature.

Routes chat completions through LiteLLM → OpenRouter → Cerebras as required
by CLAUDE.md. Structured Outputs are used to extract MNDA field values
reliably; the LLM returns one JSON object containing both the natural-
language reply and any new field values it learned this turn.

The chat is multi-document aware (PL-6): it knows the catalog of supported
documents and can recommend the closest match when a user asks for
something we don't offer. Today only the MNDA is fully generatable in the
UI, so the assistant routes other supported docs back to MNDA.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import litellm

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
legal agreements based on Common Paper templates.

## Supported documents

The catalog below lists every document type we offer. **Only the Mutual NDA \
is fully generatable in the UI today.** For any other catalog document, \
acknowledge the user's request, briefly explain that full generation for \
that document is coming soon, and offer to draft an MNDA instead if that \
would still be useful. For requests **outside** the catalog (e.g. employment \
contracts, leases, terms of service), explain that we can't generate that \
document and recommend the closest available item from the catalog.

Catalog (JSON):
{CATALOG_JSON}

## Drafting a Mutual NDA

Once the user wants an MNDA (or accepts it as a substitute), have a natural \
conversation. Ask one or two focused questions at a time. Do not dump a \
checklist of every field at once. As the user answers, extract field values \
into the structured `mnda_updates` object. Only include fields the user has \
*just* told you about — never repeat fields already filled in the current \
MNDA state. Always reply in the same language the user used (if they wrote \
Chinese, reply in Chinese), but keep field values themselves in English \
because the legal document stays English.

Fields you can populate:
- purpose: how the parties will use confidential information
- effectiveDate: ISO date string (YYYY-MM-DD)
- mndaTermMode: "expires" or "continues"
- mndaTermYears: integer (only if mndaTermMode == "expires")
- confidentialityMode: "years" or "perpetual"
- confidentialityYears: integer (only if confidentialityMode == "years")
- governingLaw: U.S. state, e.g. "Delaware"
- jurisdiction: "courts located in <city/county>, <state>"
- modifications: free-text edits to the standard terms (or "" for none)
- party1, party2: each has {{ company, signerName, signerTitle, noticeAddress }}

## Conversation rules

- Whenever `done` is false, your `assistant_message` MUST end with a \
question (terminated by "?" or "？"). The user should always see what to \
answer next — never leave the conversation hanging on a statement.
- When the MNDA looks complete enough to sign, set `done: true` and tell \
the user they can review the preview and download the PDF.
- For non-MNDA documents the chat cannot complete the draft, so keep \
`done: false` and continue offering MNDA or another available alternative.
"""


def _party_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "company": {"type": "string"},
            "signerName": {"type": "string"},
            "signerTitle": {"type": "string"},
            "noticeAddress": {"type": "string"},
        },
        "additionalProperties": False,
    }


# The structured-output schema. `mnda_updates` is intentionally a *partial*
# of the frontend MndaState — the LLM should only fill keys it actually
# extracted this turn. Required fields are forced to be present in the
# response itself (assistant_message, mnda_updates, done) but every leaf
# inside mnda_updates is optional.
CHAT_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "assistant_message": {
            "type": "string",
            "description": "Natural-language reply to show the user.",
        },
        "mnda_updates": {
            "type": "object",
            "properties": {
                "purpose": {"type": "string"},
                "effectiveDate": {"type": "string"},
                "mndaTermMode": {"enum": ["expires", "continues"]},
                "mndaTermYears": {"type": "integer", "minimum": 0},
                "confidentialityMode": {"enum": ["years", "perpetual"]},
                "confidentialityYears": {"type": "integer", "minimum": 0},
                "governingLaw": {"type": "string"},
                "jurisdiction": {"type": "string"},
                "modifications": {"type": "string"},
                "party1": _party_schema(),
                "party2": _party_schema(),
            },
            "additionalProperties": False,
        },
        "done": {
            "type": "boolean",
            "description": "True when the MNDA looks complete enough to sign.",
        },
    },
    "required": ["assistant_message", "mnda_updates", "done"],
    "additionalProperties": False,
}


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


def _call_llm(
    messages: list[dict[str, str]],
    system: str,
    api_key: str,
) -> dict[str, Any]:
    try:
        response = litellm.completion(
            model=MODEL,
            api_key=api_key,
            messages=[{"role": "system", "content": system}, *messages],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "mnda_chat_turn",
                    "schema": CHAT_RESPONSE_SCHEMA,
                    # Don't request strict mode: OpenAI strict requires every
                    # property to be listed in `required`, but `mnda_updates`
                    # is intentionally a partial — only the keys the model
                    # just learned should appear.
                },
            },
            extra_body={"provider": PROVIDER_ROUTING},
            temperature=0.3,
        )
    except Exception as exc:  # litellm wraps many transport errors
        raise LLMUnavailableError(f"LLM request failed: {exc}") from exc

    try:
        content = response.choices[0].message.content
        return json.loads(content)
    except (AttributeError, IndexError, json.JSONDecodeError, TypeError) as exc:
        raise LLMUnavailableError(
            f"LLM returned an unparseable response: {exc}",
        ) from exc


def chat_complete(
    messages: list[dict[str, str]],
    mnda_state: dict[str, Any],
) -> dict[str, Any]:
    """Call the LLM and return the parsed structured response.

    Enforces the "always ask a follow-up" contract: when `done` is false but
    the message doesn't end with a question, retry once with a corrective
    nudge. If the retry still fails, append a localized fallback question so
    the user always has something to answer.

    Raises LLMUnavailableError on auth/transport/parse failures so the
    route layer can surface a 502 with a stable shape.
    """
    api_key = _ensure_api_key()

    state_summary = json.dumps(mnda_state, indent=2, ensure_ascii=False)
    system = SYSTEM_PROMPT + f"\n\nCurrent MNDA state:\n{state_summary}"

    result = _call_llm(messages, system, api_key)

    needs_followup = (
        not result.get("done")
        and not _ends_with_question(result.get("assistant_message", ""))
    )
    if needs_followup:
        # Preserve any field values the first call already extracted — the
        # retry is purely about phrasing the reply, not re-discovering data.
        # Without this merge, a user message like "Acme is party 1" would
        # populate party1 on the first call and lose it on the retry.
        first_updates = result.get("mnda_updates") or {}
        retry_system = (
            system
            + "\n\nIMPORTANT: Your previous reply did not end with a question. "
            "While `done` is false, `assistant_message` MUST end with a question."
        )
        result = _call_llm(messages, retry_system, api_key)
        retry_updates = result.get("mnda_updates") or {}
        result["mnda_updates"] = {**first_updates, **retry_updates}
        still_missing = (
            not result.get("done")
            and not _ends_with_question(result.get("assistant_message", ""))
        )
        if still_missing:
            result["assistant_message"] = _ensure_followup(
                result.get("assistant_message") or "",
            )

    return result
