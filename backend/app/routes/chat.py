"""POST /api/chat — one turn of the MNDA drafting conversation.

The frontend keeps the full chat history and the current MNDA state in
memory and POSTs both each turn. The backend just does:

    history + current_state -> LLM (structured) -> assistant reply + updates

so it stays stateless. There is no DB write here.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.llm import LLMUnavailableError, chat_complete

router = APIRouter(prefix="/chat")


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=50)
    mnda_state: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    assistant_message: str
    mnda_updates: dict[str, Any]
    done: bool


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
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
        )
    except LLMUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )

    return ChatResponse(
        assistant_message=result["assistant_message"],
        mnda_updates=result.get("mnda_updates") or {},
        done=bool(result.get("done", False)),
    )
