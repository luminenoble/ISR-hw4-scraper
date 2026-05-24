"""GET /doc/{id} 端点单测。

用 FastAPI TestClient + dependency_overrides mock ES，覆盖：
- 正常返回 schema
- ES NotFoundError → 404
- snapshot_path / embedding 缺失 → has_* 字段为 False
- body_max 截断
"""

from __future__ import annotations

from typing import Any

import pytest
from elasticsearch import NotFoundError
from fastapi.testclient import TestClient

from api.deps import get_es
from api.main import app


class _FakeES:
    """最小化 mock：固定返回一份 _source。"""

    def __init__(self, source: dict[str, Any] | None, *, has_embedding: bool = True) -> None:
        self._source = source
        self._has_embedding = has_embedding

    def get(self, *, index: str, id: str, source_includes: list[str]) -> dict[str, Any]:
        if self._source is None:
            raise NotFoundError(
                message="not found", meta=None, body={"found": False}
            )
        return {"_source": self._source, "_id": id}

    def search(self, *, index: str, body: dict[str, Any]) -> dict[str, Any]:
        # exists embedding 探针
        return {"hits": {"total": {"value": 1 if self._has_embedding else 0}}}


@pytest.fixture
def client_factory():
    def make(fake: _FakeES) -> TestClient:
        app.dependency_overrides[get_es] = lambda: fake
        return TestClient(app)

    yield make
    app.dependency_overrides.pop(get_es, None)


def test_doc_returns_full_schema(client_factory) -> None:
    fake = _FakeES(
        {
            "doc_id": "abc",
            "source": "fandom",
            "url": "https://example.com",
            "title": "Luffy",
            "tag": "canon",
            "character_name": "Luffy",
            "body": "B" * 100,
            "infobox": {"k": "v"},
            "popularity": 1.5,
            "pagerank": 0.001,
            "obscurity": 0.7,
            "fetched_at": "2026-05-01T00:00:00Z",
            "snapshot_path": "data/snapshots/ab/cd/abc.html.gz",
        }
    )
    client = client_factory(fake)
    r = client.get("/doc/abc")
    assert r.status_code == 200
    j = r.json()
    assert j["doc_id"] == "abc"
    assert j["source"] == "fandom"
    assert j["title"] == "Luffy"
    assert j["body"] == "B" * 100
    assert j["infobox"] == {"k": "v"}
    assert j["has_snapshot"] is True
    assert j["has_embedding"] is True
    # snapshot_path 不应回传
    assert "snapshot_path" not in j


def test_doc_not_found_returns_404(client_factory) -> None:
    client = client_factory(_FakeES(None))
    r = client.get("/doc/missing")
    assert r.status_code == 404
    assert r.json()["detail"].startswith("doc not found")


def test_doc_truncates_long_body(client_factory) -> None:
    fake = _FakeES(
        {
            "doc_id": "x",
            "source": "wiki",
            "title": "Long",
            "body": "L" * 20_000,
        }
    )
    client = client_factory(fake)
    r = client.get("/doc/x?body_max=100")
    assert r.status_code == 200
    body = r.json()["body"]
    # 100 字符 + 省略号
    assert len(body) <= 110
    assert body.endswith("…")


def test_doc_no_truncate_when_body_max_zero(client_factory) -> None:
    fake = _FakeES({"doc_id": "x", "source": "wiki", "title": "L", "body": "A" * 9000})
    client = client_factory(fake)
    r = client.get("/doc/x?body_max=0")
    assert r.status_code == 200
    assert len(r.json()["body"]) == 9000


def test_doc_marks_missing_snapshot_and_embedding(client_factory) -> None:
    fake = _FakeES(
        {"doc_id": "y", "source": "reddit", "title": "T", "body": "b"},
        has_embedding=False,
    )
    client = client_factory(fake)
    r = client.get("/doc/y")
    j = r.json()
    assert j["has_snapshot"] is False
    assert j["has_embedding"] is False
