"""导库前自检脚本：固化 sec3 §3.2 的质量门。

红线项（任一不为 0 即 --strict 退出非 0）：
1. URL 残留 HTML 片段（`<`、`>`、`&lt;`、`&gt;` 等）
2. title 缺失或空
3. doc_id 缺失
4. snapshot_path 缺失
5. 快照文件缺失（Mongo 记录但磁盘上不存在）
6. 跨源 doc_id 冲突（同一 doc_id 出现在多个 source）

非红线项（仅展示）：
- 各 source 数量分布
- 孤立快照文件（磁盘有、Mongo 无）—— 仅在 --check-orphans 时扫描

CLI:
    python -m indexer.audit                  # 报告
    python -m indexer.audit --strict         # 任一红线 != 0 → exit 1
    python -m indexer.audit --check-orphans  # 额外扫描孤立快照
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pymongo
from dotenv import load_dotenv
from loguru import logger

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PROJECT_ROOT / ".env")

# URL 含 HTML 残片的判定：原始尖括号 / 实体编码 / 百分号编码
_URL_HTML_PATTERNS = re.compile(r"[<>]|&lt;|&gt;|%3C|%3E|%3c|%3e")


@dataclass
class AuditReport:
    total: int = 0
    by_source: Counter[str] = field(default_factory=Counter)
    bad_url_html: list[str] = field(default_factory=list)
    missing_title: list[str] = field(default_factory=list)
    missing_doc_id: list[str] = field(default_factory=list)
    missing_snapshot_path: list[str] = field(default_factory=list)
    snapshot_file_missing: list[str] = field(default_factory=list)
    cross_source_conflicts: list[tuple[str, list[str]]] = field(default_factory=list)
    orphan_snapshots: list[str] = field(default_factory=list)

    @property
    def red_line_count(self) -> int:
        return (
            len(self.bad_url_html)
            + len(self.missing_title)
            + len(self.missing_doc_id)
            + len(self.missing_snapshot_path)
            + len(self.snapshot_file_missing)
            + len(self.cross_source_conflicts)
        )


def _mongo_uri() -> str:
    return (
        f"mongodb://{os.getenv('MONGO_USER', 'isr')}:"
        f"{os.getenv('MONGO_PASSWORD', 'isr_dev_pw')}@"
        f"{os.getenv('MONGO_HOST', 'localhost')}:{os.getenv('MONGO_PORT', '27017')}/"
        f"?authSource=admin"
    )


def _snapshot_dir() -> Path:
    return Path(
        os.getenv("ISR_SNAPSHOT_DIR", str(_PROJECT_ROOT / "data" / "snapshots"))
    )


def audit(
    docs: list[dict],
    snapshot_dir: Path,
    max_sample: int = 10,
) -> AuditReport:
    """对一组 Mongo 文档执行自检并返回报告。

    Args:
        docs: Mongo 文档列表（已 toList）。注意大数据量请在外层流式调用而非传整表。
        snapshot_dir: 快照根目录（绝对路径），用于校验 snapshot_path 实际存在。
        max_sample: 每个红线类别最多保留多少条样本，避免报告爆炸。
    """
    report = AuditReport()
    doc_id_to_sources: dict[str, set[str]] = defaultdict(set)

    for doc in docs:
        report.total += 1
        url = doc.get("url") or ""
        source = doc.get("source") or "<unknown>"
        report.by_source[source] += 1

        if url and _URL_HTML_PATTERNS.search(url):
            if len(report.bad_url_html) < max_sample:
                report.bad_url_html.append(url)

        if not doc.get("title"):
            if len(report.missing_title) < max_sample:
                report.missing_title.append(url or str(doc.get("_id")))

        doc_id = doc.get("doc_id")
        if not doc_id:
            if len(report.missing_doc_id) < max_sample:
                report.missing_doc_id.append(url or str(doc.get("_id")))
        else:
            doc_id_to_sources[doc_id].add(source)

        snap_rel = doc.get("snapshot_path")
        if not snap_rel:
            if len(report.missing_snapshot_path) < max_sample:
                report.missing_snapshot_path.append(url or doc_id or "")
        else:
            # snapshot_path 形如 "data/snapshots/ab/cd/<doc_id>.html.gz"
            # SnapshotPipeline 写的是相对项目根的路径。这里基于项目根解析。
            full = _PROJECT_ROOT / snap_rel
            if not full.exists():
                if len(report.snapshot_file_missing) < max_sample:
                    report.snapshot_file_missing.append(str(snap_rel))

    for doc_id, srcs in doc_id_to_sources.items():
        if len(srcs) > 1:
            if len(report.cross_source_conflicts) < max_sample:
                report.cross_source_conflicts.append((doc_id, sorted(srcs)))

    return report


def find_orphan_snapshots(
    snapshot_dir: Path, mongo_paths: set[str], max_sample: int = 10
) -> list[str]:
    """扫盘找磁盘上有但 Mongo 没记录的快照。慢，仅在 --check-orphans 时跑。"""
    orphans: list[str] = []
    if not snapshot_dir.exists():
        return orphans
    project_root = snapshot_dir.parent.parent
    for path in snapshot_dir.rglob("*.gz"):
        rel = str(path.relative_to(project_root))
        if rel not in mongo_paths:
            orphans.append(rel)
            if len(orphans) >= max_sample:
                # 多采样也无意义，保留前 N 条
                break
    return orphans


def _print_report(report: AuditReport) -> None:
    logger.info(f"total docs: {report.total}")
    logger.info("by source: " + ", ".join(f"{k}={v}" for k, v in report.by_source.most_common()))

    def _line(name: str, items: list) -> None:
        n = len(items)
        if n == 0:
            logger.info(f"  [OK]   {name}: 0")
        else:
            logger.error(f"  [FAIL] {name}: {n} (sample: {items[:3]})")

    _line("URL 含 HTML 残片", report.bad_url_html)
    _line("title 缺失", report.missing_title)
    _line("doc_id 缺失", report.missing_doc_id)
    _line("snapshot_path 缺失", report.missing_snapshot_path)
    _line("快照文件缺失", report.snapshot_file_missing)
    _line("跨源 doc_id 冲突", report.cross_source_conflicts)
    if report.orphan_snapshots:
        logger.warning(
            f"  [WARN] 孤立快照（磁盘有 / Mongo 无）: {len(report.orphan_snapshots)} "
            f"(sample: {report.orphan_snapshots[:3]})"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ISR 导库前自检")
    parser.add_argument("--strict", action="store_true", help="红线 != 0 时退出 1")
    parser.add_argument(
        "--check-orphans",
        action="store_true",
        help="额外扫盘检查孤立快照（慢，10w 文件约 1-2 分钟）",
    )
    parser.add_argument(
        "--collection",
        default=os.getenv("MONGO_COLLECTION", "raw_pages"),
        help="Mongo 集合名",
    )
    args = parser.parse_args(argv)

    snapshot_dir = _snapshot_dir()
    client = pymongo.MongoClient(_mongo_uri(), serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    col = client[os.getenv("MONGO_DB", "isr")][args.collection]

    # 投影只取需要字段，省内存
    projection = {
        "doc_id": 1,
        "source": 1,
        "url": 1,
        "title": 1,
        "snapshot_path": 1,
    }
    docs = list(col.find({}, projection))
    report = audit(docs, snapshot_dir)

    if args.check_orphans:
        mongo_paths = {d.get("snapshot_path") for d in docs if d.get("snapshot_path")}
        report.orphan_snapshots = find_orphan_snapshots(snapshot_dir, mongo_paths)

    _print_report(report)

    if args.strict and report.red_line_count > 0:
        logger.error(f"strict mode: 红线项总数 {report.red_line_count}，退出 1")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
