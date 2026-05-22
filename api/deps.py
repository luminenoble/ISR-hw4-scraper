"""FastAPI 依赖注入：ES / Mongo 单例客户端。

通过 lifespan 在 app 启动时建立连接，在关闭时释放。
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pymongo
from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from loguru import logger

if TYPE_CHECKING:
    from fastapi import FastAPI

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PROJECT_ROOT / ".env")

INDEX_NAME = os.getenv("ES_INDEX", "isr_pages")
SNAPSHOT_BASE = Path(
    os.getenv("ISR_SNAPSHOT_DIR", str(_PROJECT_ROOT / "data" / "snapshots"))
).parent.parent  # 项目根，用于解析 Mongo 中的相对 snapshot_path


def _mongo_uri() -> str:
    return (
        f"mongodb://{os.getenv('MONGO_USER', 'isr')}:"
        f"{os.getenv('MONGO_PASSWORD', 'isr_dev_pw')}@"
        f"{os.getenv('MONGO_HOST', 'localhost')}:{os.getenv('MONGO_PORT', '27017')}/"
        f"?authSource=admin"
    )


class State:
    es: Elasticsearch
    mongo: pymongo.MongoClient


state = State()


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.es = Elasticsearch(
        os.getenv("ES_HOST", "http://localhost:9200"),
        request_timeout=30,
        max_retries=2,
        retry_on_timeout=True,
    )
    state.mongo = pymongo.MongoClient(_mongo_uri(), serverSelectionTimeoutMS=5000)
    state.mongo.admin.command("ping")
    if not state.es.ping():
        logger.error("ES ping failed at startup")
    db = state.mongo[os.getenv("MONGO_DB", "isr")]
    db.query_log.create_index([("user_id", 1), ("ts", -1)])
    logger.info("api started; es + mongo connected")
    try:
        yield
    finally:
        state.mongo.close()
        state.es.close()


def get_es() -> Elasticsearch:
    return state.es


def get_mongo() -> pymongo.MongoClient:
    return state.mongo


def get_pages_col():
    return state.mongo[os.getenv("MONGO_DB", "isr")][
        os.getenv("MONGO_COLLECTION", "raw_pages")
    ]


def get_log_col():
    return state.mongo[os.getenv("MONGO_DB", "isr")]["query_log"]
