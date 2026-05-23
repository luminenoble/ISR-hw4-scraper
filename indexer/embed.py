"""bge-m3 批量编码：Mongo body_text → ES embedding 字段。

依赖：
- sentence-transformers
- 模型路径：env BGE_M3_MODEL_PATH，缺省 ``BAAI/bge-m3``（走 HF / 镜像）

设计：
- 流式拉 Mongo，已编码的（Mongo 端有 ``embedded_at``）跳过；--force 全量重编
- body_text 截断到 ``--max-tokens`` 个字符（保守按字符近似 token），bge-m3 默认 8192 token，
  但 96k 篇全编 8k 太慢，512 字符已能稳出语义向量
- batch 默认 32，bulk update ES 1024 维 float32 向量
- 中断恢复：每 batch 完成后给 Mongo 写 ``embedded_at``，下次启动自动跳

CLI:
    python -m indexer.embed --batch 32                  # 增量编（默认）
    python -m indexer.embed --force                     # 不看 embedded_at 全量重编
    python -m indexer.embed --limit 100                 # 冒烟
    python -m indexer.embed --where source=document     # 只编某类
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pymongo
from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from elasticsearch import helpers as es_helpers
from loguru import logger
from tqdm import tqdm

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PROJECT_ROOT / ".env")

INDEX_NAME = os.getenv("ES_INDEX", "isr_pages")
MODEL_PATH = os.getenv("BGE_M3_MODEL_PATH", "BAAI/bge-m3")


def _mongo_uri() -> str:
    return (
        f"mongodb://{os.getenv('MONGO_USER', 'isr')}:"
        f"{os.getenv('MONGO_PASSWORD', 'isr_dev_pw')}@"
        f"{os.getenv('MONGO_HOST', 'localhost')}:{os.getenv('MONGO_PORT', '27017')}/"
        f"?authSource=admin"
    )


def load_model():
    """延迟加载 sentence-transformers，让 import 时不强依赖。"""
    from sentence_transformers import SentenceTransformer

    logger.info(f"loading bge-m3 from {MODEL_PATH}")
    model = SentenceTransformer(MODEL_PATH)
    return model


def encode_text_to_vec(text: str) -> str:
    """组合 title + body 作为编码输入；上层会做截断。"""
    return text


def iter_docs(col, where: dict, max_chars: int, batch: int, limit: int | None):
    """流式拉 Mongo body 用于编码。"""
    cursor = col.find(
        where,
        {"doc_id": 1, "title": 1, "body_text": 1},
        no_cursor_timeout=True,
    ).batch_size(batch)
    cnt = 0
    try:
        for d in cursor:
            if limit is not None and cnt >= limit:
                break
            body = (d.get("body_text") or "")[:max_chars]
            title = d.get("title") or ""
            text = f"{title}\n{body}".strip()
            if not text:
                continue
            yield d["doc_id"], text
            cnt += 1
    finally:
        cursor.close()


def mark_embedded(col, doc_ids: list[str]) -> None:
    """给 Mongo 端打 embedded_at 标记，支持下次 --resume 跳过。"""
    now = datetime.now(UTC).isoformat(timespec="seconds")
    col.update_many({"doc_id": {"$in": doc_ids}}, {"$set": {"embedded_at": now}})


def push_es(es: Elasticsearch, items: list[tuple[str, list[float]]]) -> tuple[int, int]:
    """把一批 (doc_id, vec) 写到 ES.embedding 字段。"""

    def actions():
        for did, vec in items:
            yield {
                "_op_type": "update",
                "_index": INDEX_NAME,
                "_id": did,
                "doc": {"embedding": vec},
            }

    ok = fail = 0
    for s, info in es_helpers.streaming_bulk(
        es, actions(), chunk_size=len(items), raise_on_error=False, raise_on_exception=False
    ):
        if s:
            ok += 1
        else:
            fail += 1
            if fail <= 3:
                logger.warning(f"es update fail: {info}")
    return ok, fail


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="bge-m3 编码 → ES embedding")
    p.add_argument("--batch", type=int, default=32, help="编码 + bulk 批次大小")
    p.add_argument(
        "--max-chars",
        type=int,
        default=2000,
        help="body_text 截断字符数（粗略对应 ~500-700 token）",
    )
    p.add_argument("--limit", type=int, default=None, help="只跑前 N 条")
    p.add_argument(
        "--force", action="store_true", help="无视 embedded_at，全量重编"
    )
    p.add_argument(
        "--where",
        type=str,
        default="",
        help="额外 Mongo 过滤，形如 source=document",
    )
    args = p.parse_args(argv)

    client = pymongo.MongoClient(_mongo_uri(), serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    col = client[os.getenv("MONGO_DB", "isr")][
        os.getenv("MONGO_COLLECTION", "raw_pages")
    ]

    where: dict = {}
    if args.where:
        k, _, v = args.where.partition("=")
        where[k] = v
    if not args.force:
        where["embedded_at"] = {"$exists": False}

    total = col.count_documents(where)
    logger.info(f"matched {total} docs to encode (model={MODEL_PATH})")
    if total == 0:
        return 0

    es = Elasticsearch(os.getenv("ES_HOST", "http://localhost:9200"), request_timeout=60)
    if not es.ping():
        logger.error("ES unreachable")
        return 1

    model = load_model()

    pbar = tqdm(total=args.limit or total, desc="embed")
    buf_ids: list[str] = []
    buf_text: list[str] = []
    n_ok = n_fail = 0

    def flush() -> None:
        nonlocal n_ok, n_fail
        if not buf_ids:
            return
        vecs = model.encode(
            buf_text,
            batch_size=len(buf_text),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        items = [(buf_ids[i], vecs[i].tolist()) for i in range(len(buf_ids))]
        ok, fail = push_es(es, items)
        n_ok += ok
        n_fail += fail
        mark_embedded(col, buf_ids)
        pbar.update(len(buf_ids))
        buf_ids.clear()
        buf_text.clear()

    for did, text in iter_docs(col, where, args.max_chars, args.batch, args.limit):
        buf_ids.append(did)
        buf_text.append(text)
        if len(buf_ids) >= args.batch:
            flush()
    flush()
    pbar.close()

    es.indices.refresh(index=INDEX_NAME)
    logger.info(f"done: ok={n_ok} fail={n_fail}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
