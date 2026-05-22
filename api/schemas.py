"""API 请求/响应 schema。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


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
