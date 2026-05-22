"""Mongo → Elasticsearch 流式建索引。

字段映射（PageItem → ES doc）：
- doc_id / source / url / tag / character_name / popularity / fetched_at / snapshot_path → 直传
- title → 多字段（standard + .en english + .cjk）
- anchors → 拍平为 anchors_text（空格 join 所有 anchor.text）
- body_text → body（多字段同 title）
- infobox → flattened（Mongo 端可能为 dict，原样传）
- pagerank / obscurity / embedding → 留空，待 M5 写回

CLI:
    python -m indexer.build_index --recreate            # 重建索引，从头灌
    python -m indexer.build_index --resume              # 从 last_indexed.txt 续传
    python -m indexer.build_index --limit 1000          # 只灌前 N 条（冒烟）
    python -m indexer.build_index --batch 500
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pymongo
from bson import ObjectId
from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from elasticsearch import helpers as es_helpers
from loguru import logger
from tqdm import tqdm

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PROJECT_ROOT / ".env")

INDEX_NAME = os.getenv("ES_INDEX", "isr_pages")
LAST_ID_FILE = _PROJECT_ROOT / "data" / "graph" / "last_indexed.txt"
MAPPING_FILE = Path(__file__).resolve().parent / "es_mapping.json"


def _mongo_uri() -> str:
    return (
        f"mongodb://{os.getenv('MONGO_USER', 'isr')}:"
        f"{os.getenv('MONGO_PASSWORD', 'isr_dev_pw')}@"
        f"{os.getenv('MONGO_HOST', 'localhost')}:{os.getenv('MONGO_PORT', '27017')}/"
        f"?authSource=admin"
    )


def _es_client() -> Elasticsearch:
    host = os.getenv("ES_HOST", "http://localhost:9200")
    # ES 在 localhost；绕过任何 http_proxy
    return Elasticsearch(host, request_timeout=60, max_retries=3, retry_on_timeout=True)


def _flatten_anchors(anchors: list[Any] | None) -> str:
    """将 anchors[{text,to}] 拍平为空格分隔字符串供 ES 索引。"""
    if not anchors:
        return ""
    parts: list[str] = []
    for a in anchors:
        if isinstance(a, dict):
            t = a.get("text") or ""
            if t:
                parts.append(str(t))
    return " ".join(parts)


def mongo_doc_to_es(doc: dict) -> dict:
    """将 Mongo 端的 PageItem 文档转为 ES bulk action 体。"""
    return {
        "_op_type": "index",
        "_index": INDEX_NAME,
        "_id": doc["doc_id"],
        "_source": {
            "doc_id": doc.get("doc_id"),
            "source": doc.get("source"),
            "url": doc.get("url"),
            "tag": doc.get("tag") or "canon",
            "character_name": doc.get("character_name") or None,
            "title": doc.get("title") or "",
            "anchors_text": _flatten_anchors(doc.get("anchors")),
            "body": doc.get("body_text") or "",
            "infobox": doc.get("infobox") or {},
            "popularity": float(doc.get("popularity") or 0.0),
            "fetched_at": doc.get("fetched_at"),
            "snapshot_path": doc.get("snapshot_path"),
        },
    }


def iter_mongo(
    col, batch_size: int, after_id: ObjectId | None, limit: int | None
) -> Iterator[dict]:
    """按 _id 升序流式读取 Mongo，可指定起点与上限。"""
    query: dict = {}
    if after_id is not None:
        query["_id"] = {"$gt": after_id}
    cursor = (
        col.find(
            query,
            no_cursor_timeout=True,
        )
        .sort("_id", pymongo.ASCENDING)
        .batch_size(batch_size)
    )
    try:
        for i, d in enumerate(cursor):
            if limit is not None and i >= limit:
                break
            yield d
    finally:
        cursor.close()


def load_last_id() -> ObjectId | None:
    if not LAST_ID_FILE.exists():
        return None
    raw = LAST_ID_FILE.read_text().strip()
    if not raw:
        return None
    try:
        return ObjectId(raw)
    except Exception:
        logger.warning(f"bad last_id, ignoring: {raw}")
        return None


def save_last_id(oid: ObjectId) -> None:
    LAST_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAST_ID_FILE.write_text(str(oid))


def ensure_index(es: Elasticsearch, recreate: bool) -> None:
    """按需重建索引。--recreate 强删后建；否则只在缺时建。"""
    exists = es.indices.exists(index=INDEX_NAME)
    if exists and recreate:
        logger.warning(f"deleting existing index {INDEX_NAME}")
        es.indices.delete(index=INDEX_NAME)
        exists = False
    if not exists:
        mapping = json.loads(MAPPING_FILE.read_text())
        es.indices.create(index=INDEX_NAME, body=mapping)
        logger.info(f"created index {INDEX_NAME}")
    else:
        logger.info(f"index {INDEX_NAME} already exists")


def build(
    es: Elasticsearch,
    col,
    batch_size: int,
    resume: bool,
    limit: int | None,
) -> tuple[int, int]:
    """跑一次 bulk 灌库，返回 (ok, fail)。每 batch 写一次 last_id 断点。"""
    after_id = load_last_id() if resume else None
    if resume:
        logger.info(f"resume from _id > {after_id}")

    total = col.estimated_document_count()
    logger.info(f"mongo estimated total: {total}")

    n_ok = n_fail = 0
    last_id: ObjectId | None = None

    def actions() -> Iterator[dict]:
        nonlocal last_id
        for doc in iter_mongo(col, batch_size, after_id, limit):
            last_id = doc["_id"]
            yield mongo_doc_to_es(doc)

    pbar = tqdm(total=limit if limit else total, desc="bulk")
    for ok, info in es_helpers.streaming_bulk(
        es,
        actions(),
        chunk_size=batch_size,
        max_retries=3,
        raise_on_error=False,
        raise_on_exception=False,
        request_timeout=120,
    ):
        pbar.update(1)
        if ok:
            n_ok += 1
            # 每 batch 末尾持久化一次 last_id
            if n_ok % batch_size == 0 and last_id is not None:
                save_last_id(last_id)
        else:
            n_fail += 1
            if n_fail <= 5:
                logger.warning(f"bulk fail: {info}")
    pbar.close()

    if last_id is not None:
        save_last_id(last_id)

    return n_ok, n_fail


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Mongo → ES 建索引")
    p.add_argument("--recreate", action="store_true", help="先删后建索引，从头灌")
    p.add_argument("--resume", action="store_true", help="从 last_indexed.txt 续传")
    p.add_argument("--batch", type=int, default=500, help="bulk 批次大小")
    p.add_argument("--limit", type=int, default=None, help="只灌前 N 条（冒烟用）")
    p.add_argument(
        "--collection", default=os.getenv("MONGO_COLLECTION", "raw_pages")
    )
    args = p.parse_args(argv)

    if args.recreate and args.resume:
        logger.error("--recreate 与 --resume 互斥")
        return 2

    es = _es_client()
    if not es.ping():
        logger.error("ES 不可达")
        return 1
    client = pymongo.MongoClient(_mongo_uri(), serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    col = client[os.getenv("MONGO_DB", "isr")][args.collection]

    ensure_index(es, recreate=args.recreate)
    if args.recreate and LAST_ID_FILE.exists():
        LAST_ID_FILE.unlink()
        logger.info("cleared last_indexed.txt")

    n_ok, n_fail = build(es, col, args.batch, args.resume, args.limit)
    logger.info(f"done: ok={n_ok} fail={n_fail}")

    # 刷一下让 search 立即可见
    es.indices.refresh(index=INDEX_NAME)
    count = es.count(index=INDEX_NAME)["count"]
    logger.info(f"index {INDEX_NAME} doc count: {count}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
