"""PersonalBoost 参数抽取 + click 增量更新 + script 拼装单测。

不依赖 Mongo / ES，全部纯函数。
"""

from __future__ import annotations

from api.personalization import (
    CLICK_DOC_IDS_LIMIT,
    CLICK_HISTORY_LIMIT,
    PREF_BUMP_FACTOR,
    PREF_INIT,
    apply_click_update,
    boost_params_for,
)
from api.query_parser import parse
from api.ranking import PB_W_CLICK, PB_W_SOURCE, PB_W_TAG, build_function_score
from api.routers.search import _build_inner_query


def test_boost_params_anonymous_disables():
    assert boost_params_for(None) == {"beta": 0.0}


def test_boost_params_zero_beta_disables():
    user = {"default_beta": 0.0, "preferred_sources": {"fandom": 0.5}}
    assert boost_params_for(user) == {"beta": 0.0}


def test_boost_params_full_user():
    user = {
        "default_beta": 0.5,
        "preferred_sources": {"fandom": 0.6, "wiki": 0.4},
        "preferred_tag_weights": {"canon": 0.7},
        "click_doc_ids": ["d1", "d2"],
    }
    pb = boost_params_for(user)
    assert pb["beta"] == 0.5
    assert pb["pref_sources"] == {"fandom": 0.6, "wiki": 0.4}
    assert pb["pref_tags"] == {"canon": 0.7}
    assert pb["click_set"] == ["d1", "d2"]


def test_click_update_initializes_unseen_keys():
    user: dict = {}
    upd = apply_click_update(
        user, doc_id="d1", source="fandom", tag="canon", query="luffy", dwell_ms=4200
    )
    # 首次出现 → 起始 PREF_INIT × PREF_BUMP_FACTOR
    expected = PREF_INIT * PREF_BUMP_FACTOR
    assert upd["preferred_sources"]["fandom"] == expected
    assert upd["preferred_tag_weights"]["canon"] == expected
    assert upd["click_doc_ids"] == ["d1"]
    assert upd["click_history"][0]["doc_id"] == "d1"
    assert upd["click_history"][0]["dwell_ms"] == 4200


def test_click_update_dedupes_and_moves_to_tail():
    user = {"click_doc_ids": ["a", "b", "c"]}
    upd = apply_click_update(user, doc_id="a", source=None, tag=None, query=None, dwell_ms=None)
    assert upd["click_doc_ids"] == ["b", "c", "a"]


def test_click_update_caps_history_and_ids():
    user = {
        "click_doc_ids": [f"d{i}" for i in range(CLICK_DOC_IDS_LIMIT)],
        "click_history": [{"doc_id": f"d{i}"} for i in range(CLICK_HISTORY_LIMIT)],
    }
    upd = apply_click_update(
        user, doc_id="dnew", source=None, tag=None, query=None, dwell_ms=None
    )
    assert len(upd["click_doc_ids"]) == CLICK_DOC_IDS_LIMIT
    assert upd["click_doc_ids"][-1] == "dnew"
    assert len(upd["click_history"]) == CLICK_HISTORY_LIMIT
    assert upd["click_history"][-1]["doc_id"] == "dnew"


def test_click_update_normalizes_when_overflow():
    """连续打高权重不会让任一权重超过 1.0。"""
    user = {"preferred_sources": {"fandom": 0.99}}
    upd = apply_click_update(
        user, doc_id="d1", source="fandom", tag=None, query=None, dwell_ms=None
    )
    # 0.99 * 1.02 = 1.0098 > 1 → 归一到 1.0
    assert upd["preferred_sources"]["fandom"] <= 1.0


def test_function_score_no_personal_when_beta_zero():
    pq = parse("luffy")
    fs = build_function_score(
        _build_inner_query(pq),
        alpha=0.0, w1=1.0, w2=1.0, w3=1.0,
        query_vector=None, use_embedding=False,
        beta=0.0,
        pref_sources={"fandom": 0.6},
    )
    src = fs["function_score"]["script_score"]["script"]["source"]
    params = fs["function_score"]["script_score"]["script"]["params"]
    assert "double pb_term = 0.0;" in src
    assert "beta" not in params
    assert "pref_sources" not in params


def test_function_score_includes_personal_when_beta_positive():
    pq = parse("luffy")
    fs = build_function_score(
        _build_inner_query(pq),
        alpha=0.3, w1=1.0, w2=1.0, w3=1.0,
        query_vector=None, use_embedding=False,
        beta=0.5,
        pref_sources={"fandom": 0.6, "wiki": 0.4},
        pref_tags={"canon": 0.7},
        click_set=["d1", "d2"],
    )
    src = fs["function_score"]["script_score"]["script"]["source"]
    params = fs["function_score"]["script_score"]["script"]["params"]
    # 三个分量都拼到 script
    assert "params.pref_sources" in src
    assert "params.pref_tags" in src
    assert "params.click_set" in src
    assert "params.beta * ps" in src
    # params 完整
    assert params["beta"] == 0.5
    assert params["pb_w_src"] == PB_W_SOURCE
    assert params["pb_w_tag"] == PB_W_TAG
    assert params["pb_w_clk"] == PB_W_CLICK
    assert params["click_set"] == ["d1", "d2"]


def test_function_score_personal_with_only_click_set():
    """只有 click_set 也应启用 PersonalBoost。"""
    pq = parse("luffy")
    fs = build_function_score(
        _build_inner_query(pq),
        alpha=0.0, w1=1.0, w2=1.0, w3=1.0,
        query_vector=None, use_embedding=False,
        beta=0.3,
        click_set=["d1"],
    )
    src = fs["function_score"]["script_score"]["script"]["source"]
    assert "double pb_term = 0.0;" not in src
    assert "params.click_set" in src


def test_function_score_personal_skipped_when_all_prefs_empty():
    """beta>0 但 pref_sources/tags/click 全空 → 退化为不启用。"""
    pq = parse("luffy")
    fs = build_function_score(
        _build_inner_query(pq),
        alpha=0.0, w1=1.0, w2=1.0, w3=1.0,
        query_vector=None, use_embedding=False,
        beta=0.5,
        pref_sources={},
        pref_tags={},
        click_set=[],
    )
    src = fs["function_score"]["script_score"]["script"]["source"]
    assert "double pb_term = 0.0;" in src
