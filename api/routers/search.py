"""统一搜索入口：站内 / 文档 / 短语 / 通配 通过 query_parser 分流。

排序策略（M4）：ES 默认 BM25。PageRank / Personalization 留 M5/M6。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from loguru import logger

from api.deps import INDEX_NAME, get_es, get_log_col
from api.query_parser import ParsedQuery, parse
from api.schemas import Hit, SearchResponse

router = APIRouter(prefix="", tags=["search"])

# 多字段权重：title 3x, anchors 2x, body 1x；每个语言子字段同权
_MATCH_FIELDS = [
    "title^3",
    "title.en^3",
    "title.cjk^3",
    "anchors_text^2",
    "anchors_text.en^2",
    "anchors_text.cjk^2",
    "body",
    "body.en",
    "body.cjk",
]
_PHRASE_FIELDS = ["title^3", "anchors_text^2", "body"]
# 通配走 query_string，字段限定避免扫所有 keyword
_WILDCARD_FIELDS = ["title", "url", "body"]


def _build_filters(pq: ParsedQuery) -> list[dict[str, Any]]:
    return [{"term": {k: v}} for k, v in pq.filters.items()]


def build_es_dsl(pq: ParsedQuery, size: int, from_: int) -> dict[str, Any]:
    """根据 ParsedQuery.kind 拼 ES DSL。"""
    must: list[dict[str, Any]] = []

    if pq.kind == "wildcard" and pq.wildcard:
        must.append(
            {
                "query_string": {
                    "query": pq.wildcard,
                    "fields": _WILDCARD_FIELDS,
                    "analyze_wildcard": True,
                    "default_operator": "AND",
                }
            }
        )
    elif pq.kind == "phrase":
        for ph in pq.phrases:
            must.append(
                {"multi_match": {"query": ph, "type": "phrase", "fields": _PHRASE_FIELDS}}
            )
        if pq.terms:
            must.append(
                {
                    "multi_match": {
                        "query": pq.terms,
                        "fields": _MATCH_FIELDS,
                        "type": "best_fields",
                    }
                }
            )
    else:  # kind == "match"
        if pq.terms:
            must.append(
                {
                    "multi_match": {
                        "query": pq.terms,
                        "fields": _MATCH_FIELDS,
                        "type": "best_fields",
                    }
                }
            )

    if not must:
        must.append({"match_all": {}})

    body: dict[str, Any] = {
        "from": from_,
        "size": size,
        "_source": ["doc_id", "source", "url", "title", "tag"],
        "query": {"bool": {"must": must, "filter": _build_filters(pq)}},
        "highlight": {
            "fields": {
                "body": {"fragment_size": 160, "number_of_fragments": 1},
                "title": {"fragment_size": 80, "number_of_fragments": 1},
            },
            "pre_tags": ["<em>"],
            "post_tags": ["</em>"],
        },
    }
    return body


def _hit_from_es(h: dict) -> Hit:
    src = h.get("_source", {})
    hl = h.get("highlight") or {}
    snippet: str | None = None
    if hl.get("body"):
        snippet = hl["body"][0]
    elif hl.get("title"):
        snippet = hl["title"][0]
    return Hit(
        doc_id=src.get("doc_id") or h["_id"],
        score=h.get("_score") or 0.0,
        source=src.get("source"),
        url=src.get("url"),
        title=src.get("title"),
        tag=src.get("tag"),
        snippet=snippet,
    )


@router.get("/search", response_model=SearchResponse)
def search(
    q: Annotated[str, Query(description="查询字符串，支持引号短语 / *? 通配 / site:source:tag:")],
    size: int = 10,
    from_: Annotated[int, Query(alias="from", ge=0)] = 0,
    source: str | None = Query(None, description="显式过滤 source（document 等）"),
    user_id: str | None = Query(None, description="用户 id，用于查询日志"),
    es=Depends(get_es),
    log_col=Depends(get_log_col),
) -> SearchResponse:
    pq = parse(q)
    # 显式 source 参数等价于 source: 前缀，方便前端做 "文档查询" tab
    if source:
        pq.filters["source"] = source
    dsl = build_es_dsl(pq, size=size, from_=from_)

    resp = es.search(index=INDEX_NAME, body=dsl)
    took = int(resp.get("took") or 0)
    total = resp["hits"]["total"]["value"]
    hits = [_hit_from_es(h) for h in resp["hits"]["hits"]]

    # 写查询日志（对应作业 2.3.5）
    try:
        log_col.insert_one(
            {
                "user_id": user_id,
                "query": q,
                "kind": pq.kind,
                "filters": pq.filters,
                "ts": datetime.now(UTC).isoformat(timespec="seconds"),
                "total": total,
                "result_ids": [h.doc_id for h in hits],
            }
        )
    except Exception as e:
        logger.warning(f"query_log insert failed: {e}")

    return SearchResponse(
        query=q,
        kind=pq.kind,
        total=total,
        took_ms=took,
        hits=hits,
        filters=pq.filters,
    )
