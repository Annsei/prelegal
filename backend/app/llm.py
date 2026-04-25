"""LLM client for the MNDA chat feature.

Routes chat completions through LiteLLM → OpenRouter → Cerebras as required
by CLAUDE.md. Structured Outputs are used to extract MNDA field values
reliably; the LLM returns one JSON object containing both the natural-
language reply and any new field values it learned this turn.
"""

from __future__ import annotations

import json
import os
from typing import Any

import litellm

MODEL = "openrouter/openai/gpt-oss-120b"

# Force Cerebras as the inference provider so we don't silently fall back
# to a slower one and lose response-time consistency. See the project's
# .claude/skills/cerebras/SKILL.md for the rationale.
PROVIDER_ROUTING = {"order": ["cerebras"], "allow_fallbacks": False}


SYSTEM_PROMPT = """\
You are a friendly legal-drafting assistant helping the user prepare a Mutual \
Non-Disclosure Agreement (MNDA) based on the Common Paper template. \

Have a natural conversation. Ask one or two focused questions at a time. \
Do not dump a checklist of every field at once. As the user answers, extract \
field values into the structured `mnda_updates` object. Only include fields \
the user has *just* told you about — never repeat fields already filled in \
the current MNDA state. Always reply in the same language the user used \
(if they wrote Chinese, reply in Chinese), but keep field values themselves \
in English because the legal document stays English.

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
- party1, party2: each has { company, signerName, signerTitle, noticeAddress }

When the MNDA looks complete enough to sign, set `done: true` and tell the \
user they can review the preview and download the PDF. Until then, keep \
`done: false`.
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


def chat_complete(
    messages: list[dict[str, str]],
    mnda_state: dict[str, Any],
) -> dict[str, Any]:
    """Call the LLM and return the parsed structured response.

    Raises LLMUnavailableError on auth/transport/parse failures so the
    route layer can surface a 502 with a stable shape.
    """
    api_key = _ensure_api_key()

    state_summary = json.dumps(mnda_state, indent=2, ensure_ascii=False)
    system = SYSTEM_PROMPT + f"\n\nCurrent MNDA state:\n{state_summary}"

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
