"""搜索联想：两路召回按 α 混合（design.md §3.6）。

- Path A 前缀补全（α 小时主导）：
    1) MongoDB query_log 聚合：startswith(q) 的历史 query，按频次排序
    2) ES match_phrase_prefix 在 title^3 + body，召回热门页标题
- Path B 语义近邻（α 大时主导）：
    用 bge-m3 编码 q → ES kNN against embedding 取 top-K
    再砍掉最热门的 5%（按 popularity 倒序），保留 5..K 区间的"小众语义近邻"

为什么不引入 ES completion 子字段：
    match_phrase_prefix + query_log 聚合即可覆盖前缀补全需求，
    避免 96k 文档 reindex + PageRank/embedding 重灌的开销。
    后续若需输入实时性能 < 20ms 再考虑专用 completion 索引。
"""

from __future__ import annotations

from collections import Counter
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from loguru import logger
from pydantic import BaseModel

from api.deps import (
    INDEX_NAME,
    get_current_user_optional,
    get_embedder,
    get_es,
    get_log_col,
)

router = APIRouter(prefix="", tags=["suggest"])

# 语义路径砍最热门 5%，避免和 BM25/PR 路径完全重合
KNN_DROP_TOP_RATIO = 0.05
# kNN 召回候选池大小；从中砍头后挑剩下
KNN_K = 50
KNN_NUM_CANDIDATES = 200
# 历史 query 至多扫多少条做前缀匹配
QLOG_SCAN_LIMIT = 5000
# 单 query 文本上限，防极端长 q
Q_MAX_LEN = 80


class Suggestion(BaseModel):
    text: str
    score: float
    kind: Literal["history", "title", "semantic"]
    doc_id: str | None = None


class SuggestResponse(BaseModel):
    q: str
    alpha: float
    suggestions: list[Suggestion]


def _path_a_history(q: str, log_col, limit: int = 20) -> list[Suggestion]:
    """MongoDB query_log 聚合：startswith(q) 的历史 query 按频次排。"""
    if not q:
        return []
    # 直接读最近 QLOG_SCAN_LIMIT 条，按前缀过滤；规模 < 几万够用
    cur = log_col.find(
        {"query": {"$regex": f"^{q}", "$options": "i"}},
        {"query": 1},
    ).sort("ts", -1).limit(QLOG_SCAN_LIMIT)
    counter: Counter[str] = Counter()
    for row in cur:
        s = (row.get("query") or "").strip()
        if s and s.lower() != q.lower():
            counter[s] += 1
    out: list[Suggestion] = []
    for text, n in counter.most_common(limit):
        # 频次 → [0,1] 朴素归一
        out.append(Suggestion(text=text, score=min(1.0, 0.3 + 0.7 * n / 5.0), kind="history"))
    return out


def _path_a_title(q: str, es, limit: int = 20) -> list[Suggestion]:
    """ES match_phrase_prefix on title（多语种子字段都参与）。"""
    if not q:
        return []
    body: dict[str, Any] = {
        "size": limit,
        "_source": ["doc_id", "title"],
        "query": {
            "bool": {
                "should": [
                    {"match_phrase_prefix": {"title": {"query": q, "boost": 3.0}}},
                    {"match_phrase_prefix": {"title.en": {"query": q, "boost": 2.0}}},
                    {"match_phrase_prefix": {"title.cjk": {"query": q, "boost": 2.0}}},
                ],
                "minimum_should_match": 1,
            }
        },
    }
    resp = es.search(index=INDEX_NAME, body=body)
    hits = resp["hits"]["hits"]
    if not hits:
        return []
    top = hits[0]["_score"] or 1.0
    out: list[Suggestion] = []
    for h in hits:
        src = h.get("_source") or {}
        title = (src.get("title") or "").strip()
        if not title:
            continue
        out.append(
            Suggestion(
                text=title,
                score=(h["_score"] or 0.0) / top,  # 同批 max-norm
                kind="title",
                doc_id=src.get("doc_id"),
            )
        )
    return out


def _path_b_semantic(q: str, es, limit: int = 20) -> list[Suggestion]:
    """bge-m3 编码 q → ES kNN against embedding，砍最热门 5% 后取头部。"""
    embedder = get_embedder()
    if embedder is None:
        logger.debug("suggest: embedder 未就绪，语义路径跳过")
        return []
    try:
        vec = embedder.encode([q], normalize_embeddings=True, convert_to_numpy=True)[0]
    except Exception as e:
        logger.warning(f"suggest: query encode failed ({e})")
        return []
    body = {
        "size": KNN_K,
        "_source": ["doc_id", "title", "popularity"],
        "knn": {
            "field": "embedding",
            "query_vector": vec.tolist(),
            "k": KNN_K,
            "num_candidates": KNN_NUM_CANDIDATES,
        },
    }
    resp = es.search(index=INDEX_NAME, body=body)
    hits = resp["hits"]["hits"]
    if not hits:
        return []
    # 按 popularity 降序砍头 5%
    drop_n = max(1, int(len(hits) * KNN_DROP_TOP_RATIO))
    by_pop = sorted(
        hits, key=lambda h: float((h.get("_source") or {}).get("popularity") or 0.0), reverse=True
    )
    drop_ids = {h["_id"] for h in by_pop[:drop_n]}
    seen: set[str] = set()
    out: list[Suggestion] = []
    for h in hits:
        if h["_id"] in drop_ids:
            continue
        src = h.get("_source") or {}
        title = (src.get("title") or "").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        out.append(
            Suggestion(
                text=title,
                score=h.get("_score") or 0.0,  # kNN 余弦相似度，已在 [0,1]+
                kind="semantic",
                doc_id=src.get("doc_id"),
            )
        )
        if len(out) >= limit:
            break
    return out


def _merge_by_alpha(
    a_hist: list[Suggestion],
    a_title: list[Suggestion],
    b_sem: list[Suggestion],
    *,
    alpha: float,
    size: int,
) -> list[Suggestion]:
    """按 α 混合：A 路按 (1-α)、B 路按 α 加权。同 text 去重保最高分。"""
    weight_a = max(0.0, 1.0 - alpha)
    weight_b = alpha
    pool: dict[str, Suggestion] = {}
    for s in a_hist + a_title:
        s2 = s.model_copy(update={"score": s.score * weight_a})
        cur = pool.get(s2.text.lower())
        if cur is None or s2.score > cur.score:
            pool[s2.text.lower()] = s2
    for s in b_sem:
        s2 = s.model_copy(update={"score": s.score * weight_b})
        cur = pool.get(s2.text.lower())
        if cur is None or s2.score > cur.score:
            pool[s2.text.lower()] = s2
    out = sorted(pool.values(), key=lambda x: x.score, reverse=True)
    return out[:size]


@router.get("/suggest", response_model=SuggestResponse)
def suggest(
    q: Annotated[str, Query(min_length=1, max_length=Q_MAX_LEN)],
    size: int = 8,
    alpha: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    es=Depends(get_es),
    log_col=Depends(get_log_col),
    current_user: dict | None = Depends(get_current_user_optional),
) -> SuggestResponse:
    if alpha is None:
        alpha = float(current_user.get("default_alpha", 0.3)) if current_user else 0.3

    q_clean = q.strip()[:Q_MAX_LEN]
    a_hist = _path_a_history(q_clean, log_col)
    a_title = _path_a_title(q_clean, es)
    b_sem = _path_b_semantic(q_clean, es) if alpha > 0 else []

    # 降级：α>0 但语义路径没结果（embedder 未就绪 / 字段缺失） → 退化为纯 A 路，
    # 否则 α=1 时整个结果会被 (1-α)=0 抹平。
    effective_alpha = alpha if b_sem else 0.0
    merged = _merge_by_alpha(a_hist, a_title, b_sem, alpha=effective_alpha, size=size)
    return SuggestResponse(q=q_clean, alpha=alpha, suggestions=merged)
