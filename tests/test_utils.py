"""crawler.isr_crawler.utils 的最小可跑单测。"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许直接 pytest tests/ 而不依赖 PYTHONPATH 配置
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "crawler"))

from isr_crawler.utils import (  # noqa: E402
    clean_text,
    doc_id_for,
    extract_anchors,
    now_iso_utc,
    snapshot_path_for,
)


def test_doc_id_is_sha1_of_url() -> None:
    a = doc_id_for("https://example.org/x")
    b = doc_id_for("https://example.org/x")
    c = doc_id_for("https://example.org/y")
    assert len(a) == 40
    assert a == b
    assert a != c


def test_snapshot_path_bucketed() -> None:
    doc_id = "ab" + "cd" + "0" * 36
    p = snapshot_path_for(doc_id, "/tmp/snap")
    assert p.parts[-3:] == ("ab", "cd", f"{doc_id}.html.gz")


def test_clean_text_strips_html_and_collapses_whitespace() -> None:
    html = "<p>hello   <b>world</b></p><script>x()</script>"
    out = clean_text(html)
    assert out == "hello world"


def test_extract_anchors_filters_empty_and_fragments() -> None:
    html = '<a href="/a">A</a><a href="#top">skip</a><a href="">empty</a><a href="/b">  </a>'
    anchors = extract_anchors(html)
    assert anchors == [{"text": "A", "to": "/a"}]


def test_now_iso_utc_format() -> None:
    s = now_iso_utc()
    assert s.endswith("Z")
    assert "T" in s
    assert len(s) == len("2026-05-19T00:00:00Z")
