"""离线 PageRank + Popularity + Obscurity 计算，结果回写 ES。

构图：
- 节点：raw_pages 中全部 doc_id
- 边：每个 doc 的 anchors[].to 经 urljoin(doc.url, to) + 规范化后，能匹配
  到 Mongo 内某个 url 时，加一条有向边 src_doc → dst_doc

派生：
- PageRank：networkx.pagerank(alpha=0.85)
- Popularity：in-degree（入链数，作为受欢迎度代理）
- Obscurity：1 / log(in_degree + e)，无入链时为 1.0

落盘：
- ``data/graph/pagerank.csv``：doc_id,pagerank,popularity,obscurity
- 同步 bulk `_update` 写 ES 三个字段

CLI:
    python -m indexer.pagerank             # 全量重算并回写
    python -m indexer.pagerank --dry-run   # 只算不写 ES
    python -m indexer.pagerank --csv-only  # 算 + 落盘，不动 ES
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import networkx as nx
import pymongo
from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from elasticsearch import helpers as es_helpers
from loguru import logger
from tqdm import tqdm

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PROJECT_ROOT / ".env")

INDEX_NAME = os.getenv("ES_INDEX", "isr_pages")
GRAPH_DIR = _PROJECT_ROOT / "data" / "graph"
CSV_PATH = GRAPH_DIR / "pagerank.csv"


def normalize_url(u: str) -> str:
    """轻量规范化：小写 host、去 fragment、保留 query。

    跨源 doc 的 URL 字符串差异巨大，过度规范化会误合并；这里只做安全的规范化。
    遇 ValueError（非 NFKC 主机名）原样返回，依赖上层匹配失败即跳过。
    """
    if not u:
        return ""
    try:
        p = urlparse(u)
    except ValueError:
        return u
    host = (p.netloc or "").lower()
    path = p.path or ""
    q = f"?{p.query}" if p.query else ""
    scheme = p.scheme or "http"
    return f"{scheme}://{host}{path}{q}"


def _mongo_uri() -> str:
    return (
        f"mongodb://{os.getenv('MONGO_USER', 'isr')}:"
        f"{os.getenv('MONGO_PASSWORD', 'isr_dev_pw')}@"
        f"{os.getenv('MONGO_HOST', 'localhost')}:{os.getenv('MONGO_PORT', '27017')}/"
        f"?authSource=admin"
    )


def build_graph(col) -> tuple[nx.DiGraph, int]:
    """两遍扫表：第一遍建 url→doc_id 索引，第二遍连边。

    返回 (图, 命中的内链数)。
    """
    logger.info("pass 1: building url→doc_id index ...")
    url_to_id: dict[str, str] = {}
    docs_meta: list[tuple[str, str, list]] = []
    for d in tqdm(col.find({}, {"doc_id": 1, "url": 1, "anchors": 1}), desc="scan"):
        did = d.get("doc_id")
        url = d.get("url") or ""
        if not did or not url:
            continue
        url_to_id[normalize_url(url)] = did
        docs_meta.append((did, url, d.get("anchors") or []))

    logger.info(f"docs={len(docs_meta)}, unique normalized urls={len(url_to_id)}")

    logger.info("pass 2: adding edges ...")
    g: nx.DiGraph = nx.DiGraph()
    g.add_nodes_from(did for did, _, _ in docs_meta)

    edges_added = 0
    for did, base, anchors in tqdm(docs_meta, desc="edges"):
        for a in anchors:
            if not isinstance(a, dict):
                continue
            to = a.get("to") or ""
            if not to or to.startswith(("javascript:", "mailto:")):
                continue
            try:
                abs_url = urljoin(base, to)
            except ValueError:
                continue
            norm = normalize_url(abs_url)
            tgt = url_to_id.get(norm)
            if tgt and tgt != did:
                # has_edge 简单去重；DiGraph 允许平行边，但 pagerank 不区分
                if not g.has_edge(did, tgt):
                    g.add_edge(did, tgt)
                    edges_added += 1

    logger.info(f"graph: nodes={g.number_of_nodes()} edges={edges_added}")
    return g, edges_added


def compute_metrics(
    g: nx.DiGraph, damping: float = 0.85
) -> tuple[dict[str, float], dict[str, int], dict[str, float]]:
    """PageRank + in-degree + obscurity 一次算齐。"""
    logger.info(f"running pagerank (alpha={damping}) ...")
    pr = nx.pagerank(g, alpha=damping, tol=1e-6, max_iter=100)
    in_deg = {n: int(d) for n, d in g.in_degree()}
    obscurity = {n: 1.0 / math.log(in_deg.get(n, 0) + math.e) for n in g.nodes}
    return pr, in_deg, obscurity


def write_csv(pr: dict, in_deg: dict, obs: dict) -> Path:
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["doc_id", "pagerank", "popularity", "obscurity"])
        for did, p in pr.items():
            w.writerow([did, f"{p:.10f}", in_deg.get(did, 0), f"{obs[did]:.6f}"])
    logger.info(f"csv written: {CSV_PATH}")
    return CSV_PATH


def bulk_update_es(
    es: Elasticsearch, pr: dict, in_deg: dict, obs: dict, batch: int = 1000
) -> tuple[int, int]:
    def actions():
        for did, p in pr.items():
            yield {
                "_op_type": "update",
                "_index": INDEX_NAME,
                "_id": did,
                "doc": {
                    "pagerank": float(p),
                    "popularity": float(in_deg.get(did, 0)),
                    "obscurity": float(obs[did]),
                },
            }

    n_ok = n_fail = 0
    for ok, info in es_helpers.streaming_bulk(
        es,
        actions(),
        chunk_size=batch,
        max_retries=3,
        raise_on_error=False,
        raise_on_exception=False,
    ):
        if ok:
            n_ok += 1
        else:
            n_fail += 1
            if n_fail <= 5:
                logger.warning(f"update fail: {info}")
    return n_ok, n_fail


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="PageRank + Popularity + Obscurity 离线计算")
    p.add_argument("--dry-run", action="store_true", help="只算不写 ES、不落盘")
    p.add_argument("--csv-only", action="store_true", help="算 + 落盘，不动 ES")
    p.add_argument("--damping", type=float, default=0.85)
    p.add_argument("--batch", type=int, default=1000)
    p.add_argument(
        "--collection", default=os.getenv("MONGO_COLLECTION", "raw_pages")
    )
    args = p.parse_args(argv)

    client = pymongo.MongoClient(_mongo_uri(), serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    col = client[os.getenv("MONGO_DB", "isr")][args.collection]

    g, n_edges = build_graph(col)
    if g.number_of_nodes() == 0:
        logger.error("empty graph; nothing to do")
        return 1

    pr, in_deg, obs = compute_metrics(g, damping=args.damping)

    # 简短统计：top-5 by PageRank（debug 用）
    top5 = sorted(pr.items(), key=lambda x: -x[1])[:5]
    logger.info("top-5 PageRank:")
    for did, p in top5:
        d = col.find_one({"doc_id": did}, {"url": 1, "title": 1, "source": 1})
        if d:
            logger.info(
                f"  {p:.6f} | {d.get('source')} | {(d.get('title') or '')[:60]} | indeg={in_deg.get(did,0)}"
            )

    if args.dry_run:
        logger.info("dry-run: skipping csv and ES write")
        return 0

    write_csv(pr, in_deg, obs)

    if args.csv_only:
        return 0

    es = Elasticsearch(os.getenv("ES_HOST", "http://localhost:9200"), request_timeout=60)
    if not es.ping():
        logger.error("ES unreachable")
        return 1
    n_ok, n_fail = bulk_update_es(es, pr, in_deg, obs, batch=args.batch)
    es.indices.refresh(index=INDEX_NAME)
    logger.info(f"ES update: ok={n_ok} fail={n_fail}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
