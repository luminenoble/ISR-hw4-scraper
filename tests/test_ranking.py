"""排序公式拼装单测：检验 function_score script 在不同 α / 有无向量时正确分支。"""

from __future__ import annotations

from api.query_parser import parse
from api.ranking import build_function_score
from api.routers.search import _build_inner_query, build_es_dsl


def test_inner_query_match():
    pq = parse("luffy")
    inner = _build_inner_query(pq)
    assert "bool" in inner
    must = inner["bool"]["must"]
    assert any("multi_match" in m for m in must)


def test_inner_query_phrase_combines_phrase_and_terms():
    pq = parse('"strawhat pirates" pirate')
    inner = _build_inner_query(pq)
    must = inner["bool"]["must"]
    # 短语 + 残余 terms 两条
    assert len(must) == 2
    assert any(m.get("multi_match", {}).get("type") == "phrase" for m in must)


def test_function_score_no_embedding_falls_back_to_obscurity():
    pq = parse("luffy")
    fs = build_function_score(
        _build_inner_query(pq),
        alpha=0.7,
        w1=1.0,
        w2=1.0,
        w3=1.0,
        query_vector=None,
        use_embedding=False,
    )
    script_src = fs["function_score"]["script_score"]["script"]["source"]
    # 没向量时 sem 占位为 1，alpha 路径就是 obs
    assert "double sem = 1.0;" in script_src
    # qv 不应出现在 params 里
    assert "qv" not in fs["function_score"]["script_score"]["script"]["params"]


def test_function_score_with_embedding_uses_cosine():
    pq = parse("luffy")
    fake_vec = [0.1] * 1024
    fs = build_function_score(
        _build_inner_query(pq),
        alpha=0.5,
        w1=1.0,
        w2=1.0,
        w3=1.0,
        query_vector=fake_vec,
        use_embedding=True,
    )
    script_src = fs["function_score"]["script_score"]["script"]["source"]
    assert "cosineSimilarity(params.qv, 'embedding')" in script_src
    params = fs["function_score"]["script_score"]["script"]["params"]
    assert params["alpha"] == 0.5
    assert len(params["qv"]) == 1024


def test_alpha_zero_skips_embedding_path_at_call_site():
    """当 alpha=0 时调用 build_function_score 仍可传向量，公式里 (1-α)*bm + α*sem
    自然把 sem 项归 0。验证 script 结构总体合法即可。"""
    pq = parse("luffy")
    fs = build_function_score(
        _build_inner_query(pq),
        alpha=0.0,
        w1=1.0,
        w2=1.0,
        w3=1.0,
        query_vector=None,
        use_embedding=False,
    )
    src = fs["function_score"]["script_score"]["script"]["source"]
    assert "(1.0 - params.alpha)" in src
    assert "params.alpha * sem_term" in src


def test_build_es_dsl_attaches_highlight_to_inner_not_function_score():
    """高亮应基于原始 BM25 子句（避免 script 干扰）。"""
    pq = parse("luffy")
    dsl = build_es_dsl(
        pq, size=10, from_=0, alpha=0.0, w1=1.0, w2=1.0, w3=1.0, query_vector=None
    )
    assert "highlight" in dsl
    assert dsl["highlight"]["highlight_query"]["bool"]["must"][0]["multi_match"]["query"] == "luffy"


def test_filter_propagates_into_function_score_inner_query():
    pq = parse("source:document luffy")
    dsl = build_es_dsl(
        pq, size=10, from_=0, alpha=0.0, w1=1.0, w2=1.0, w3=1.0, query_vector=None
    )
    fs_inner = dsl["query"]["function_score"]["query"]
    assert {"term": {"source": "document"}} in fs_inner["bool"]["filter"]
