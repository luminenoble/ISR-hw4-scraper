"""Scrapy 全局设置。

读取根目录 `.env`（与 docker-compose 共用一份），通过环境变量注入：
- ISR_CONTACT_EMAIL: 必填，UA 中的联系方式
- MONGO_USER / MONGO_PASSWORD / MONGO_PORT / MONGO_DB
- ISR_SNAPSHOT_DIR: 默认 data/snapshots
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# 加载项目根 .env（crawler/ 的父目录）
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")

BOT_NAME = "isr_crawler"

SPIDER_MODULES = ["isr_crawler.spiders"]
NEWSPIDER_MODULE = "isr_crawler.spiders"

# --- 合规 ---
_CONTACT = os.getenv("ISR_CONTACT_EMAIL", "isr-course@example.com")
USER_AGENT = f"ISR-CourseProject/0.1 (+mailto:{_CONTACT})"
ROBOTSTXT_OBEY = True

# --- 并发与限速 ---
CONCURRENT_REQUESTS = 8
CONCURRENT_REQUESTS_PER_DOMAIN = 4
DOWNLOAD_DELAY = 0.5

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_MAX_DELAY = 10.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 2.0

# --- 重试 ---
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [429, 500, 502, 503, 504, 522, 524, 408]

# --- 缓存（开发期开启，避免反复打 API） ---
HTTPCACHE_ENABLED = bool(int(os.getenv("ISR_HTTPCACHE", "1")))
HTTPCACHE_EXPIRATION_SECS = 60 * 60 * 24 * 3  # 3 天
HTTPCACHE_DIR = str(_PROJECT_ROOT / ".scrapy" / "httpcache")
HTTPCACHE_IGNORE_HTTP_CODES = [429, 500, 502, 503, 504]
HTTPCACHE_STORAGE = "scrapy.extensions.httpcache.FilesystemCacheStorage"

# --- Pipelines ---
ITEM_PIPELINES = {
    "isr_crawler.pipelines.CleanPipeline": 100,
    "isr_crawler.pipelines.SnapshotPipeline": 200,
    "isr_crawler.pipelines.MongoPipeline": 300,
}

# --- Mongo 连接 ---
MONGO_URI = (
    f"mongodb://{os.getenv('MONGO_USER', 'isr')}:"
    f"{os.getenv('MONGO_PASSWORD', 'isr_dev_pw')}@"
    f"{os.getenv('MONGO_HOST', 'localhost')}:{os.getenv('MONGO_PORT', '27017')}/"
    f"?authSource=admin"
)
MONGO_DB = os.getenv("MONGO_DB", "isr")
MONGO_COLLECTION = "raw_pages"

# --- 快照目录 ---
SNAPSHOT_DIR = os.getenv("ISR_SNAPSHOT_DIR", str(_PROJECT_ROOT / "data" / "snapshots"))

# --- 日志 ---
LOG_LEVEL = os.getenv("SCRAPY_LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"

# --- 编码 ---
FEED_EXPORT_ENCODING = "utf-8"
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
