"""API 请求/响应 schema。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Hit(BaseModel):
    doc_id: str
    score: float
    source: str | None = None
    url: str | None = None
    title: str | None = None
    tag: str | None = None
    snippet: str | None = None


class SearchResponse(BaseModel):
    query: str
    kind: str
    total: int
    took_ms: int
    hits: list[Hit]
    filters: dict[str, str] = {}


class LogEntry(BaseModel):
    user_id: str | None = None
    query: str
    kind: str
    ts: str
    total: int
    result_ids: list[str] = []
    extra: dict[str, Any] = {}


# --- auth / users ---


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=6, max_length=200)
    interests: list[str] = []
    preferred_sources: dict[str, float] = {}
    preferred_tag_weights: dict[str, float] = {}
    default_alpha: float = Field(default=0.3, ge=0.0, le=1.0)
    default_beta: float = Field(default=0.5, ge=0.0, le=5.0)


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str


class UserProfile(BaseModel):
    """对外暴露的用户档案（剔除 password_hash / interest_vec）。"""

    user_id: str
    email: str
    created_at: str
    interests: list[str] = []
    preferred_sources: dict[str, float] = {}
    preferred_tag_weights: dict[str, float] = {}
    default_alpha: float = 0.3
    default_beta: float = 0.5
    click_count: int = 0


class ProfilePatch(BaseModel):
    interests: list[str] | None = None
    preferred_sources: dict[str, float] | None = None
    preferred_tag_weights: dict[str, float] | None = None
    default_alpha: float | None = Field(default=None, ge=0.0, le=1.0)
    default_beta: float | None = Field(default=None, ge=0.0, le=5.0)


class ClickRequest(BaseModel):
    doc_id: str
    query: str | None = None
    dwell_ms: int | None = Field(default=None, ge=0)
