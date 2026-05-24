"""评测脚本公共工具：ES 客户端 / 查询样本 / 指标计算。

为 M8 评测准备：复用与 api/ 同源的 ES 连接配置，但不依赖 FastAPI 运行时。
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from elasticsearch import Elasticsearch

# 让脚本独立可运行：从项目根加载 .env
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PROJECT_ROOT / ".env")

INDEX_NAME = os.getenv("ES_INDEX", "isr_pages")
ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")


def get_es() -> Elasticsearch:
    return Elasticsearch(ES_HOST, request_timeout=60)


# M8 评测样本 query：覆盖中英文 / 知名↔小众 / canon↔fanon
SAMPLE_QUERIES: list[str] = [
    "Luffy",
    "Harry Potter",
    "Naruto",
    "Genshin Impact",
    "fan theory",
    "character backstory",
    "悟空",
    "原神",
    "fanfiction trope",
    "alternate universe",
]


# 6 种查询的代表样本，写死避免每次随机
QUERY_CASES: dict[str, str] = {
    "match": "Luffy strawhat",
    "document": "source:document character",
    "phrase": '"alternate universe"',
    "wildcard": "naru*",
    # 下面两个用于触发服务侧能力，不直接走 ES
    "log": "Luffy",
    "snapshot": "Luffy",
}


def jaccard(a: list[str], b: list[str]) -> float:
    """两个有序结果集的 Jaccard 相似度（忽略顺序）。"""
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / max(1, len(sa | sb))


def rbo(a: list[str], b: list[str], p: float = 0.9) -> float:
    """Rank-Biased Overlap：对前缀给予指数衰减权重的有序重叠度。

    p ∈ (0,1)：靠 1 越关注深层，靠 0 越关注头部。返回 [0,1]。
    """
    if not a and not b:
        return 1.0
    k = min(len(a), len(b))
    if k == 0:
        return 0.0
    overlap = 0
    sa, sb = set(), set()
    score = 0.0
    for d in range(k):
        sa.add(a[d])
        sb.add(b[d])
        overlap = len(sa & sb)
        score += (overlap / (d + 1)) * (p**d)
    return (1.0 - p) * score


def timed(fn):
    """简易耗时装饰：返回 (结果, 毫秒)。"""

    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        out = fn(*args, **kwargs)
        return out, (time.perf_counter() - t0) * 1000

    return wrapper
