from __future__ import annotations

from typing import Any

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str = Field(default="", max_length=200)
    # 8-char floor matches the message rendered on the login page; raise
    # this once we add stricter password rules. Hard cap is bcrypt's 72.
    password: str = Field(min_length=8, max_length=72)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class UserOut(BaseModel):
    id: int
    email: EmailStr
    name: str
    created_at: str


class SessionOut(BaseModel):
    """Login/register response: user record + the bearer token to use next."""

    user: UserOut
    token: str


class DocumentSummary(BaseModel):
    """Sidebar-list shape — omits the heavy state_json blob."""

    id: int
    doc_id: str
    title: str
    created_at: str
    updated_at: str


class DocumentOut(BaseModel):
    id: int
    doc_id: str
    title: str
    state: dict[str, Any]
    created_at: str
    updated_at: str


class DocumentCreateRequest(BaseModel):
    doc_id: str = Field(min_length=1, max_length=100)
    title: str = Field(default="", max_length=200)
    state: dict[str, Any] = Field(default_factory=dict)


class DocumentUpdateRequest(BaseModel):
    # Both fields optional so PUTs can carry a partial change without
    # round-tripping the whole record. Server treats missing keys as
    # "leave unchanged".
    title: str | None = Field(default=None, max_length=200)
    state: dict[str, Any] | None = None
