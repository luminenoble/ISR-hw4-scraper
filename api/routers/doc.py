"""单文档详情路由（M8 补完 M7 占位）。

读 ES `_source`：拿到 body + infobox + 全部排序信号，给前端详情页渲染。
不返回 ``embedding`` / ``snapshot_path`` 大字段，避免 1KB+ 向量回传。
"""

from __future__ import annotations

from typing import Any

from elasticsearch import NotFoundError
from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import INDEX_NAME, get_es
from api.schemas import DocDetail

router = APIRouter(prefix="", tags=["doc"])

# body 字段可能极长（reddit 长帖 / wiki 长文），默认裁到 8000 字符够详情阅读
_DEFAULT_BODY_MAX = 8000

# 拉取的字段白名单（剔除 embedding / snapshot_path）
_SOURCE_INCLUDES = [
    "doc_id",
    "source",
    "url",
    "title",
    "tag",
    "character_name",
    "body",
    "infobox",
    "popularity",
    "pagerank",
    "obscurity",
    "fetched_at",
]


def _truncate(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


@router.get("/doc/{doc_id}", response_model=DocDetail)
def get_doc(
    doc_id: str,
    body_max: int = Query(
        _DEFAULT_BODY_MAX,
        ge=0,
        le=100_000,
        description="body 最长字符数；0 表示不截断",
    ),
    es=Depends(get_es),
) -> DocDetail:
    """根据 doc_id 取单文档全字段。命中走 ES `_id` 直查，O(1)。"""
    try:
        resp = es.get(
            index=INDEX_NAME,
            id=doc_id,
            source_includes=_SOURCE_INCLUDES + ["snapshot_path"],
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"doc not found: {doc_id}") from None

    src: dict[str, Any] = resp.get("_source") or {}
    has_snapshot = bool(src.pop("snapshot_path", None))
    # embedding 字段不在 includes 里，但单独探一下有没有：取 _source 不含 embedding 时
    # 再查 exists（轻量 term）。这里偷懒：用 fields 查询 embedding 是否存在。
    has_embedding = False
    try:
        probe = es.search(
            index=INDEX_NAME,
            body={
                "size": 0,
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"_id": doc_id}},
                            {"exists": {"field": "embedding"}},
                        ]
                    }
                },
                "track_total_hits": True,
            },
        )
        has_embedding = (probe["hits"]["total"]["value"] or 0) > 0
    except Exception:
        has_embedding = False

    return DocDetail(
        doc_id=src.get("doc_id") or doc_id,
        source=src.get("source"),
        url=src.get("url"),
        title=src.get("title"),
        tag=src.get("tag"),
        character_name=src.get("character_name"),
        body=_truncate(src.get("body"), body_max),
        infobox=src.get("infobox") or {},
        popularity=src.get("popularity"),
        pagerank=src.get("pagerank"),
        obscurity=src.get("obscurity"),
        fetched_at=src.get("fetched_at"),
        has_snapshot=has_snapshot,
        has_embedding=has_embedding,
    )
