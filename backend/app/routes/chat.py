"""POST /api/chat — one turn of the MNDA drafting conversation.

The frontend keeps the full chat history and the current MNDA state in
memory and POSTs both each turn. The backend just does:

    history + current_state -> LLM (structured) -> assistant reply + updates

so it stays stateless. There is no DB write here.

Requires a bearer token: every turn costs real money on OpenRouter, so
anonymous callers can't run up the bill. Rate-limited per user on top.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.auth import current_user
from app.llm import LLMUnavailableError, chat_complete
from app.ratelimit import CHAT_LIMITER, enforce

router = APIRouter(prefix="/chat")

# The state is injected verbatim into the system prompt; an unbounded blob
# would inflate LLM token cost (or blow the context window) long before it
# hurts anything else.
MAX_STATE_BYTES = 64 * 1024


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=50)
    mnda_state: dict[str, Any] = Field(default_factory=dict)
    # The doc the frontend currently has open. Lets the LLM layer inject
    # that document's cover-page field checklist (see app/manifests.py).
    # Empty on the first turn, before a document is picked.
    doc_id: str = Field(default="", max_length=100)

    @field_validator("mnda_state")
    @classmethod
    def _cap_state_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        encoded = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        if encoded > MAX_STATE_BYTES:
            raise ValueError(
                f"mnda_state too large ({encoded} bytes > {MAX_STATE_BYTES})",
            )
        return value


class ChatResponse(BaseModel):
    assistant_message: str
    selected_doc_id: str = ""
    mnda_updates: dict[str, Any]
    field_updates: dict[str, str]
    done: bool


@router.post("", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    user: sqlite3.Row = Depends(current_user),
) -> ChatResponse:
    enforce(CHAT_LIMITER, f"chat:{user['id']}")
    if payload.messages[-1].role != "user":
        # The LLM only has something to reply to if the conversation ends
        # with a user turn. Reject early so we don't waste a request.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="last message must be from the user",
        )

    try:
        result = chat_complete(
            messages=[m.model_dump() for m in payload.messages],
            mnda_state=payload.mnda_state,
            doc_id=payload.doc_id,
        )
    except LLMUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return ChatResponse(
        assistant_message=result["assistant_message"],
        selected_doc_id=result.get("selected_doc_id") or "",
        mnda_updates=result.get("mnda_updates") or {},
        field_updates=result.get("field_updates") or {},
        done=bool(result.get("done", False)),
    )
