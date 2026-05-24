"""统一搜索入口：站内 / 文档 / 短语 / 通配 通过 query_parser 分流。

排序策略（M4）：ES 默认 BM25。PageRank / Personalization 留 M5/M6。
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from loguru import logger

from api.deps import (
    INDEX_NAME,
    get_current_user_optional,
    get_embedder,
    get_es,
    get_log_col,
)
from api.personalization import boost_params_for
from api.query_parser import ParsedQuery, parse
from api.ranking import (
    DEFAULT_BETA,
    DEFAULT_W1,
    DEFAULT_W2,
    DEFAULT_W3,
    build_function_score,
)
from api.schemas import Hit, HitCard, SearchCardsResponse, SearchResponse

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


def _alpha_curve(alpha: float) -> float:
    """UI 上 [0,1] 的 α 映射到 script 用的 effective α。

    余弦再映射 ``0.5 × (1 − cos(π·α))``：边界不变（0→0, 1→1, 0.5→0.5），
    中点附近斜率最大（=π/2），把"中段切换不出感觉"那段陡峭化。
    评测见 reports/eval_alpha.md（M8 修后重跑）。
    """
    if alpha <= 0.0:
        return 0.0
    if alpha >= 1.0:
        return 1.0
    return 0.5 * (1.0 - math.cos(math.pi * alpha))


def _build_filters(pq: ParsedQuery) -> list[dict[str, Any]]:
    return [{"term": {k: v}} for k, v in pq.filters.items()]


def _build_inner_query(pq: ParsedQuery) -> dict[str, Any]:
    """根据 kind 拼 bool 查询（BM25 必含部分），filter 一并放在内层。"""
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

    return {"bool": {"must": must, "filter": _build_filters(pq)}}


def build_es_dsl(
    pq: ParsedQuery,
    size: int,
    from_: int,
    alpha: float,
    w1: float,
    w2: float,
    w3: float,
    query_vector: list[float] | None,
    beta: float = 0.0,
    pref_sources: dict[str, float] | None = None,
    pref_tags: dict[str, float] | None = None,
    click_set: list[str] | None = None,
) -> dict[str, Any]:
    """拼最终 ES 查询体：内层 BM25 + 外层 function_score 公式打分。"""
    inner = _build_inner_query(pq)
    use_emb = query_vector is not None
    fs = build_function_score(
        inner,
        alpha=alpha,
        w1=w1,
        w2=w2,
        w3=w3,
        query_vector=query_vector,
        use_embedding=use_emb,
        beta=beta,
        pref_sources=pref_sources,
        pref_tags=pref_tags,
        click_set=click_set,
    )
    return {
        "from": from_,
        "size": size,
        "_source": ["doc_id", "source", "url", "title", "tag"],
        "query": fs,
        "highlight": {
            "fields": {
                "body": {"fragment_size": 160, "number_of_fragments": 1},
                "title": {"fragment_size": 80, "number_of_fragments": 1},
            },
            "highlight_query": inner,  # 高亮基于原始 BM25 子句，避免 script_score 干扰
            "pre_tags": ["<em>"],
            "post_tags": ["</em>"],
        },
    }


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
    rating: str | None = Query(None, description="AO3 rating 过滤（如 'Mature'）"),
    language: str | None = Query(None, description="AO3 language 过滤（如 'English'）"),
    user_id: str | None = Query(None, description="用户 id，用于查询日志"),
    alpha: Annotated[float | None, Query(ge=0.0, le=1.0, description="发散度 0=纯 BM25+PR / 1=纯语义；缺省取用户档案 default_alpha")] = None,
    beta: Annotated[float | None, Query(ge=0.0, le=5.0, description="个性化总权重；缺省取用户档案 default_beta，匿名为 0")] = None,
    w1: float = DEFAULT_W1,
    w2: float = DEFAULT_W2,
    w3: float = DEFAULT_W3,
    es=Depends(get_es),
    log_col=Depends(get_log_col),
    current_user: dict | None = Depends(get_current_user_optional),
) -> SearchResponse:
    pq = parse(q)
    if source:
        pq.filters["source"] = source
    if rating:
        pq.filters["rating"] = rating
    if language:
        pq.filters["language"] = language

    # 参数优先级：URL > 用户档案 > 全局默认
    if alpha is None:
        alpha = float(current_user.get("default_alpha", 0.0)) if current_user else 0.0
    if beta is None:
        beta = float(current_user.get("default_beta", DEFAULT_BETA)) if current_user else 0.0

    # 登录用户 → 总是回填 pref_sources/tags/click_set；URL beta 决定权重
    # 匿名用户 → 一律 beta=0
    pb = boost_params_for(current_user)
    pb["beta"] = beta if current_user else 0.0
    if pb["beta"] <= 0:
        # 关闭个性化：清掉 boost 字段免 script_score 误开 personal_src 分支
        pb = {"beta": 0.0}

    user_id = current_user["user_id"] if current_user else user_id

    # α 非线性映射：UI 的 0..1 在传给 script 前过余弦曲线把中间区段拉开，
    # 让 0.3↔0.7 区段不再高度黏合（M8 评测发现 Jaccard 高达 0.899）。
    # 边界不变：eff(0)=0, eff(1)=1；中点附近斜率被拉大。
    effective_alpha = _alpha_curve(alpha)

    # alpha > 0 且模型已就绪时，对 q 编码一份 query_vector 参与语义项
    query_vector: list[float] | None = None
    if effective_alpha > 0 and (pq.terms or pq.phrases):
        embedder = get_embedder()
        if embedder is not None:
            seed = " ".join(pq.phrases + ([pq.terms] if pq.terms else [])).strip()
            try:
                vec = embedder.encode(
                    [seed], normalize_embeddings=True, convert_to_numpy=True
                )[0]
                query_vector = vec.tolist()
            except Exception as e:
                logger.warning(f"query embed failed; alpha 路径降级: {e}")

    dsl = build_es_dsl(
        pq,
        size=size,
        from_=from_,
        alpha=effective_alpha,
        w1=w1,
        w2=w2,
        w3=w3,
        query_vector=query_vector,
        beta=pb.get("beta", 0.0),
        pref_sources=pb.get("pref_sources"),
        pref_tags=pb.get("pref_tags"),
        click_set=pb.get("click_set"),
    )

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
                "alpha": alpha,
                "effective_alpha": effective_alpha,
                "beta": pb.get("beta", 0.0),
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


def _strip_em(s: str | None) -> str | None:
    if not s:
        return s
    # 去 <em> 标签但保留文本（移动端自行渲染）
    return s.replace("<em>", "").replace("</em>", "")


@router.get("/search/cards", response_model=SearchCardsResponse)
def search_cards(
    q: Annotated[str, Query()],
    size: int = 10,
    from_: Annotated[int, Query(alias="from", ge=0)] = 0,
    source: str | None = Query(None),
    alpha: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    beta: Annotated[float | None, Query(ge=0.0, le=5.0)] = None,
    es=Depends(get_es),
    log_col=Depends(get_log_col),
    current_user: dict | None = Depends(get_current_user_optional),
) -> SearchCardsResponse:
    """精简版 /search，给移动端预留。复用主路径再裁字段。"""
    full = search(
        q=q, size=size, from_=from_, source=source, user_id=None,
        alpha=alpha, beta=beta,
        w1=DEFAULT_W1, w2=DEFAULT_W2, w3=DEFAULT_W3,
        es=es, log_col=log_col, current_user=current_user,
    )
    cards = [
        HitCard(
            doc_id=h.doc_id,
            score=h.score,
            title=h.title,
            source=h.source,
            tag=h.tag,
            snippet_plain=_strip_em(h.snippet),
        )
        for h in full.hits
    ]
    return SearchCardsResponse(
        query=full.query,
        kind=full.kind,
        total=full.total,
        took_ms=full.took_ms,
        hits=cards,
    )
