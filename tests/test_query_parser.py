"""api.query_parser 单测：6 种查询场景的解析路径。"""

from __future__ import annotations

from api.query_parser import parse


def test_plain_match():
    p = parse("luffy gear5")
    assert p.kind == "match"
    assert p.terms == "luffy gear5"
    assert p.phrases == []
    assert p.filters == {}
    assert p.wildcard is None


def test_phrase_query():
    p = parse('"strawhat pirates"')
    assert p.kind == "phrase"
    assert p.phrases == ["strawhat pirates"]
    assert p.terms == ""


def test_phrase_with_residual_terms():
    p = parse('"gear five" luffy')
    assert p.kind == "phrase"
    assert p.phrases == ["gear five"]
    assert p.terms == "luffy"


def test_wildcard_star():
    p = parse("luff*")
    assert p.kind == "wildcard"
    assert p.wildcard == "luff*"


def test_wildcard_question_mark():
    p = parse("zor?")
    assert p.kind == "wildcard"


def test_filter_site_alias_to_source():
    p = parse("site:fandom luffy")
    assert p.filters == {"source": "fandom"}
    assert p.terms == "luffy"
    assert p.kind == "match"


def test_filter_source_document():
    p = parse("source:document harry potter")
    assert p.filters == {"source": "document"}
    assert "harry potter" in p.terms
    assert p.kind == "match"


def test_filter_tag():
    p = parse("tag:fanon ship")
    assert p.filters == {"tag": "fanon"}


def test_combined_filter_phrase():
    p = parse('source:fandom "monkey d luffy" pirate')
    assert p.filters == {"source": "fandom"}
    assert p.phrases == ["monkey d luffy"]
    assert p.terms == "pirate"
    assert p.kind == "phrase"


def test_empty():
    p = parse("")
    assert p.kind == "match"
    assert p.terms == ""


def test_unknown_filter_key_passes_through():
    """unknown_key:value 不在白名单 → 不剥离，照常进 terms。"""
    p = parse("foo:bar luffy")
    assert "foo:bar" in p.terms or "luffy" in p.terms
    assert p.filters == {}
