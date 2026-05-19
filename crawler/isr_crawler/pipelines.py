"""Item 处理管线：清洗 → 快照落盘 → MongoDB 写入。

执行顺序由 settings.ITEM_PIPELINES 控制：CleanPipeline(100) → SnapshotPipeline(200) → MongoPipeline(300)。

Scrapy 2.13+ 的新签名：pipeline 方法不再接收 ``spider`` 参数。
如需访问 spider，通过 ``from_crawler`` 把 ``crawler`` 存下来再用 ``self.crawler.spider``。
"""

from __future__ import annotations

import gzip
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pymongo
from itemadapter import ItemAdapter
from loguru import logger
from scrapy.exceptions import DropItem

from .utils import (
    clean_text,
    doc_id_for,
    extract_anchors,
    now_iso_utc,
    snapshot_path_for,
)

if TYPE_CHECKING:
    from scrapy.crawler import Crawler


class CleanPipeline:
    """补齐 doc_id / fetched_at，清洗正文与锚文本。"""

    def process_item(self, item: Any) -> Any:
        adapter = ItemAdapter(item)

        url = adapter.get("url")
        if not url:
            raise DropItem("missing url")

        adapter["doc_id"] = adapter.get("doc_id") or doc_id_for(url)
        adapter["fetched_at"] = adapter.get("fetched_at") or now_iso_utc()

        raw_html = adapter.get("raw_html") or ""
        if raw_html and not adapter.get("body_text"):
            adapter["body_text"] = clean_text(raw_html)
        if raw_html and not adapter.get("anchors"):
            adapter["anchors"] = extract_anchors(raw_html, base_url=url)

        # 兜底默认值
        adapter.setdefault("tag", "canon")
        adapter.setdefault("popularity", 0.0)
        adapter.setdefault("infobox", {})
        adapter.setdefault("anchors", [])
        adapter.setdefault("extra", {})

        return item


class SnapshotPipeline:
    """将 raw_html 以 gzip 形式落到 data/snapshots/ab/cd/<doc_id>.html.gz。"""

    def __init__(self, snapshot_dir: str) -> None:
        self.snapshot_dir = Path(snapshot_dir)

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> SnapshotPipeline:
        return cls(snapshot_dir=crawler.settings.get("SNAPSHOT_DIR"))

    def open_spider(self) -> None:
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"[snapshot] base dir = {self.snapshot_dir}")

    def process_item(self, item: Any) -> Any:
        adapter = ItemAdapter(item)
        raw_html = adapter.get("raw_html")
        if not raw_html:
            return item

        doc_id = adapter["doc_id"]
        path = snapshot_path_for(doc_id, self.snapshot_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wb", compresslevel=6) as f:
            f.write(raw_html.encode("utf-8"))

        adapter["snapshot_path"] = str(path.relative_to(self.snapshot_dir.parent.parent))
        # 落盘后即可丢弃 raw_html，避免 Mongo 文档过大
        adapter["raw_html"] = None
        return item


class MongoPipeline:
    """按 doc_id upsert 到 MongoDB。"""

    def __init__(self, mongo_uri: str, mongo_db: str, mongo_collection: str) -> None:
        self.mongo_uri = mongo_uri
        self.mongo_db = mongo_db
        self.mongo_collection = mongo_collection
        self.client: pymongo.MongoClient | None = None

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> MongoPipeline:
        return cls(
            mongo_uri=crawler.settings.get("MONGO_URI"),
            mongo_db=crawler.settings.get("MONGO_DB"),
            mongo_collection=crawler.settings.get("MONGO_COLLECTION", "raw_pages"),
        )

    def open_spider(self) -> None:
        self.client = pymongo.MongoClient(self.mongo_uri, serverSelectionTimeoutMS=5000)
        self.client.admin.command("ping")
        db = self.client[self.mongo_db]
        self.collection = db[self.mongo_collection]
        self.collection.create_index("doc_id", unique=True)
        self.collection.create_index("source")
        self.collection.create_index("fetched_at")
        logger.info(f"[mongo] connected db={self.mongo_db} col={self.mongo_collection}")

    def close_spider(self) -> None:
        if self.client is not None:
            self.client.close()

    def process_item(self, item: Any) -> Any:
        adapter = ItemAdapter(item)
        doc = dict(adapter.asdict())
        # raw_html 已在 SnapshotPipeline 中清空，不写入 Mongo
        doc.pop("raw_html", None)
        self.collection.update_one(
            {"doc_id": doc["doc_id"]},
            {"$set": doc},
            upsert=True,
        )
        return item
