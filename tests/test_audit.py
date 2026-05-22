"""indexer.audit 单测：构造脏样本验证每条红线断言。"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from indexer.audit import audit, find_orphan_snapshots


@pytest.fixture
def snapshot_root(tmp_path: Path) -> Path:
    """构造 data/snapshots 目录结构。"""
    root = tmp_path / "data" / "snapshots"
    root.mkdir(parents=True)
    return root


def _write_snapshot(snapshot_root: Path, doc_id: str) -> str:
    """在 snapshots/ab/cd/<doc_id>.html.gz 写一个空 gz，返回相对项目根的路径。"""
    sub = snapshot_root / doc_id[:2] / doc_id[2:4]
    sub.mkdir(parents=True, exist_ok=True)
    path = sub / f"{doc_id}.html.gz"
    with gzip.open(path, "wb") as f:
        f.write(b"<html></html>")
    # audit.py 用 _PROJECT_ROOT = indexer/.. 解析；这里只验证相对结构，绕开 _PROJECT_ROOT
    return str(path.relative_to(snapshot_root.parent.parent))


def test_audit_all_clean(snapshot_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # patch _PROJECT_ROOT 到 tmp_path
    import indexer.audit as audit_mod

    monkeypatch.setattr(audit_mod, "_PROJECT_ROOT", snapshot_root.parent.parent)

    docs = [
        {
            "doc_id": "a" * 40,
            "source": "fandom",
            "url": "https://onepiece.fandom.com/wiki/Luffy",
            "title": "Monkey D. Luffy",
            "snapshot_path": _write_snapshot(snapshot_root, "a" * 40),
        }
    ]
    report = audit(docs, snapshot_root)
    assert report.red_line_count == 0
    assert report.total == 1
    assert report.by_source["fandom"] == 1


def test_audit_catches_each_red_line(
    snapshot_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import indexer.audit as audit_mod

    monkeypatch.setattr(audit_mod, "_PROJECT_ROOT", snapshot_root.parent.parent)

    docs = [
        # URL 含 HTML 残片（原始尖括号）
        {
            "doc_id": "1" * 40,
            "source": "wiki",
            "url": "https://en.wikipedia.org/wiki/<script>",
            "title": "Bad",
            "snapshot_path": _write_snapshot(snapshot_root, "1" * 40),
        },
        # URL 含 HTML 残片（百分号编码）
        {
            "doc_id": "2" * 40,
            "source": "wiki",
            "url": "https://en.wikipedia.org/wiki/%3Cdiv%3E",
            "title": "Bad2",
            "snapshot_path": _write_snapshot(snapshot_root, "2" * 40),
        },
        # title 缺失
        {
            "doc_id": "3" * 40,
            "source": "wiki",
            "url": "https://en.wikipedia.org/wiki/NoTitle",
            "title": "",
            "snapshot_path": _write_snapshot(snapshot_root, "3" * 40),
        },
        # doc_id 缺失
        {
            "source": "wiki",
            "url": "https://en.wikipedia.org/wiki/NoDocId",
            "title": "NoDocId",
            "snapshot_path": _write_snapshot(snapshot_root, "4" * 40),
        },
        # snapshot_path 缺失
        {
            "doc_id": "5" * 40,
            "source": "wiki",
            "url": "https://en.wikipedia.org/wiki/NoSnap",
            "title": "NoSnap",
        },
        # snapshot_path 有，但磁盘文件不存在
        {
            "doc_id": "6" * 40,
            "source": "wiki",
            "url": "https://en.wikipedia.org/wiki/GhostSnap",
            "title": "GhostSnap",
            "snapshot_path": "data/snapshots/66/66/" + "6" * 40 + ".html.gz",
        },
    ]
    report = audit(docs, snapshot_root)

    assert len(report.bad_url_html) == 2
    assert len(report.missing_title) == 1
    assert len(report.missing_doc_id) == 1
    assert len(report.missing_snapshot_path) == 1
    assert len(report.snapshot_file_missing) == 1
    assert report.red_line_count == 6


def test_audit_cross_source_conflict(
    snapshot_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import indexer.audit as audit_mod

    monkeypatch.setattr(audit_mod, "_PROJECT_ROOT", snapshot_root.parent.parent)

    doc_id = "f" * 40
    docs = [
        {
            "doc_id": doc_id,
            "source": "wiki",
            "url": "https://en.wikipedia.org/wiki/X",
            "title": "X",
            "snapshot_path": _write_snapshot(snapshot_root, doc_id),
        },
        {
            "doc_id": doc_id,
            "source": "fandom",
            "url": "https://x.fandom.com/wiki/X",
            "title": "X",
            "snapshot_path": _write_snapshot(snapshot_root, doc_id),
        },
    ]
    report = audit(docs, snapshot_root)
    assert len(report.cross_source_conflicts) == 1
    assert report.cross_source_conflicts[0][0] == doc_id
    assert report.cross_source_conflicts[0][1] == ["fandom", "wiki"]


def test_find_orphan_snapshots(snapshot_root: Path) -> None:
    rel1 = _write_snapshot(snapshot_root, "a" * 40)
    rel2 = _write_snapshot(snapshot_root, "b" * 40)
    # 只有 rel1 在 Mongo 里
    orphans = find_orphan_snapshots(snapshot_root, {rel1})
    assert orphans == [rel2]
