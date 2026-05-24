"""联想路由：合并逻辑 + α 加权 + 去重。

ES / Mongo 调用单测里不打，端到端用冒烟脚本。
"""

from __future__ import annotations

from api.routers.suggest import Suggestion, _merge_by_alpha


def _s(text: str, score: float, kind: str = "title") -> Suggestion:
    return Suggestion(text=text, score=score, kind=kind)  # type: ignore[arg-type]


def test_merge_alpha_zero_only_path_a():
    out = _merge_by_alpha(
        [_s("history-a", 0.9, "history")],
        [_s("title-a", 0.8, "title")],
        [_s("sem-a", 1.0, "semantic")],
        alpha=0.0,
        size=10,
    )
    texts = [s.text for s in out]
    # alpha=0 → 语义项 weight 0，应被沉到末尾或被 A 路压住
    assert texts[0] == "history-a"
    sem = next(s for s in out if s.text == "sem-a")
    assert sem.score == 0.0


def test_merge_alpha_one_only_path_b():
    out = _merge_by_alpha(
        [_s("history-a", 0.9, "history")],
        [_s("title-a", 0.8, "title")],
        [_s("sem-a", 1.0, "semantic")],
        alpha=1.0,
        size=10,
    )
    texts = [s.text for s in out]
    assert texts[0] == "sem-a"
    hist = next(s for s in out if s.text == "history-a")
    assert hist.score == 0.0


def test_merge_dedupes_case_insensitive():
    """同一文本在 A/B 两路重复出现 → 取最高分。"""
    out = _merge_by_alpha(
        [_s("Luffy", 0.8, "history")],
        [_s("LUFFY", 0.5, "title")],
        [_s("luffy", 0.9, "semantic")],
        alpha=0.5,
        size=10,
    )
    luffys = [s for s in out if s.text.lower() == "luffy"]
    assert len(luffys) == 1
    # A 路最高 0.8*0.5=0.4，B 路 0.9*0.5=0.45 → 取 B
    assert luffys[0].kind == "semantic"
    assert abs(luffys[0].score - 0.45) < 1e-6


def test_merge_respects_size():
    a = [_s(f"a{i}", 1.0 - i * 0.01, "title") for i in range(20)]
    out = _merge_by_alpha(a, [], [], alpha=0.0, size=5)
    assert len(out) == 5


def test_merge_sorted_desc_by_score():
    out = _merge_by_alpha(
        [_s("x", 0.3, "history"), _s("y", 0.7, "history")],
        [],
        [_s("z", 0.9, "semantic")],
        alpha=0.5,
        size=10,
    )
    scores = [s.score for s in out]
    assert scores == sorted(scores, reverse=True)
