"""Tika 文档解析：从已抓页面中筛 .pdf → 下载 → Tika 抽文本 → 入 Mongo。

设计要点（沿用 sec3 §3.1 的 schema 不另起灶）：

- ``source = "document"`` 与网页区分（对应作业 2.3.2 文档查询）
- ``doc_id = sha1(pdf_url)`` 与网页同算法，跨源不冲突
- 快照走 ``data/snapshots/<ab>/<cd>/<doc_id>.pdf.gz``，保存原始 PDF 字节
- ``body_text`` 取 Tika 纯文本输出；``title`` 取 Tika 元数据 dc:title，回退到 URL basename
- 不绕过 robots——下载用与爬虫相同的 UA，仅守 ``--delay`` 限速；遇 403/429 直接跳过

CLI:
    python -m parser.doc_parser --limit 300 --delay 1.0
    python -m parser.doc_parser --limit 5 --dry-run   # 只列候选不下载
"""

from __future__ import annotations

import argparse
import gzip
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
import pymongo
from dotenv import load_dotenv
from loguru import logger
from tqdm import tqdm

# 复用爬虫工具，doc_id 与 snapshot 路径规则保持一致
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "crawler"))
from isr_crawler.utils import doc_id_for, now_iso_utc, snapshot_path_for  # noqa: E402

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PROJECT_ROOT / ".env")

# PDF URL 判定：末尾 .pdf 或 .pdf? / .pdf# / .pdf& 等
_PDF_RE = re.compile(r"\.pdf(\?|#|&|$)", re.I)


@dataclass
class TikaResult:
    text: str
    title: str | None


def is_pdf_url(url: str) -> bool:
    if not url or not url.startswith(("http://", "https://")):
        return False
    # 部分 URL 含非 NFKC 字符会让 urlparse 抛 ValueError，直接对原串匹配兜底
    try:
        path = urlparse(url).path
    except ValueError:
        return bool(_PDF_RE.search(url))
    return bool(_PDF_RE.search(path)) or bool(_PDF_RE.search(url))


def collect_pdf_candidates(col, limit: int | None = None) -> list[str]:
    """扫 raw_pages 全表，从 url + anchors[].to 中聚合 .pdf 链接。

    去重大小写不敏感地基于 URL 本身。返回稳定排序的列表。
    """
    candidates: set[str] = set()
    cursor = col.find({}, {"url": 1, "anchors": 1})
    for doc in cursor:
        url = doc.get("url") or ""
        if is_pdf_url(url):
            candidates.add(url)
        for a in doc.get("anchors") or []:
            to = a.get("to") if isinstance(a, dict) else None
            if to and is_pdf_url(to):
                candidates.add(to)
    out = sorted(candidates)
    if limit is not None:
        out = out[:limit]
    return out


def filename_from_url(url: str) -> str:
    name = Path(unquote(urlparse(url).path)).name or "document.pdf"
    # 去掉扩展名当 title 兜底
    return Path(name).stem or "document"


def tika_extract(
    pdf_bytes: bytes, tika_url: str, timeout: float = 60.0
) -> TikaResult | None:
    """PUT bytes 到 Tika，分两次请求：先要文本，再要元数据。

    Tika 也支持 ``/rmeta/text`` 一次返回元数据 + 文本，但 8w+ 项目里这样更稳。
    """
    try:
        # Tika 在 localhost，绕过任何全局 http_proxy（WSL 上常见）
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            r1 = client.put(
                f"{tika_url.rstrip('/')}/tika",
                content=pdf_bytes,
                headers={"Accept": "text/plain; charset=UTF-8"},
            )
            r1.raise_for_status()
            text = r1.text or ""

            r2 = client.put(
                f"{tika_url.rstrip('/')}/meta",
                content=pdf_bytes,
                headers={"Accept": "application/json"},
            )
            title: str | None = None
            if r2.status_code == 200:
                meta = r2.json() if r2.content else {}
                # Tika 把 dc:title / title 都暴露过，取最先非空
                for k in ("dc:title", "title", "pdf:docinfo:title"):
                    v = meta.get(k)
                    if isinstance(v, list):
                        v = v[0] if v else None
                    if v and str(v).strip():
                        title = str(v).strip()
                        break
    except (httpx.HTTPError, ValueError) as e:
        logger.warning(f"tika failed: {e}")
        return None

    return TikaResult(text=text.strip(), title=title)


def download_pdf(
    url: str, user_agent: str, timeout: float = 15.0, max_bytes: int = 50 * 1024 * 1024
) -> bytes | None:
    """直链下载 PDF，500MB 上限，非 200 / 非 application/pdf 直接弃。"""
    try:
        with httpx.Client(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": user_agent}
        ) as client:
            r = client.get(url)
            if r.status_code != 200:
                logger.debug(f"skip {r.status_code}: {url[:120]}")
                return None
            ct = r.headers.get("content-type", "").lower()
            if "pdf" not in ct and not url.lower().endswith(".pdf"):
                logger.debug(f"skip non-pdf ct={ct}: {url[:120]}")
                return None
            data = r.content
            if len(data) > max_bytes:
                logger.debug(f"skip too large {len(data)}: {url[:120]}")
                return None
            if not data.startswith(b"%PDF"):
                logger.debug(f"skip not-pdf-magic: {url[:120]}")
                return None
            return data
    except httpx.HTTPError as e:
        logger.debug(f"download error: {e} | {url[:120]}")
        return None


def save_doc(
    col,
    snapshot_dir: Path,
    url: str,
    pdf_bytes: bytes,
    parsed: TikaResult,
) -> dict:
    """把解析结果落 Mongo + 原始 PDF gzip 落盘。返回写入的文档（已含 _id 字段除外）。"""
    doc_id = doc_id_for(url)
    snap_path = snapshot_path_for(doc_id, snapshot_dir, ext="pdf.gz")
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(snap_path, "wb", compresslevel=6) as f:
        f.write(pdf_bytes)
    snap_rel = str(snap_path.relative_to(snapshot_dir.parent.parent))

    title = parsed.title or filename_from_url(url)

    item = {
        "doc_id": doc_id,
        "source": "document",
        "url": url,
        "title": title,
        "character_name": None,
        "infobox": {},
        "body_text": parsed.text,
        "anchors": [],
        "tag": "canon",
        "popularity": 0.0,
        "fetched_at": now_iso_utc(),
        "snapshot_path": snap_rel,
        "extra": {"mime": "application/pdf", "size_bytes": len(pdf_bytes)},
    }
    col.update_one({"doc_id": doc_id}, {"$set": item}, upsert=True)
    return item


def _mongo_uri() -> str:
    return (
        f"mongodb://{os.getenv('MONGO_USER', 'isr')}:"
        f"{os.getenv('MONGO_PASSWORD', 'isr_dev_pw')}@"
        f"{os.getenv('MONGO_HOST', 'localhost')}:{os.getenv('MONGO_PORT', '27017')}/"
        f"?authSource=admin"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tika 文档解析（PDF）")
    parser.add_argument("--limit", type=int, default=300, help="本次解析数量上限")
    parser.add_argument("--delay", type=float, default=1.0, help="下载间隔秒，守限速")
    parser.add_argument(
        "--tika-url",
        default=f"http://localhost:{os.getenv('TIKA_PORT', '9998')}",
        help="Tika 服务地址",
    )
    parser.add_argument(
        "--collection",
        default=os.getenv("MONGO_COLLECTION", "raw_pages"),
        help="Mongo 集合（与网页同集合，source 区分）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只列候选不下载")
    parser.add_argument(
        "--seed", type=int, default=42, help="候选随机洗牌种子（同 seed 复现）"
    )
    parser.add_argument(
        "--prefer-https", action="store_true", default=True, help="先抽 https 候选"
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="跳过 Mongo 已存在 doc_id（默认开）",
    )
    args = parser.parse_args(argv)

    snapshot_dir = Path(
        os.getenv("ISR_SNAPSHOT_DIR", str(_PROJECT_ROOT / "data" / "snapshots"))
    )
    client = pymongo.MongoClient(_mongo_uri(), serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    col = client[os.getenv("MONGO_DB", "isr")][args.collection]

    logger.info("scanning Mongo for .pdf candidates ...")
    candidates = collect_pdf_candidates(col, limit=None)
    logger.info(f"found {len(candidates)} unique .pdf URLs")

    if args.skip_existing:
        existing = {
            d["doc_id"]
            for d in col.find({"source": "document"}, {"doc_id": 1})
        }
        candidates = [u for u in candidates if doc_id_for(u) not in existing]
        logger.info(f"after skip-existing: {len(candidates)} remain")

    # 字典序首部全是死站点（数字 IP / 暴露端口），随机化 + 偏好 https
    rng = random.Random(args.seed)
    if args.prefer_https:
        https = [u for u in candidates if u.startswith("https://")]
        http = [u for u in candidates if u.startswith("http://")]
        rng.shuffle(https)
        rng.shuffle(http)
        candidates = https + http
    else:
        rng.shuffle(candidates)
    candidates = candidates[: args.limit]
    logger.info(f"will process {len(candidates)} (limit={args.limit})")

    if args.dry_run:
        for u in candidates[:20]:
            print(u)
        return 0

    ua = (
        f"{os.getenv('ISR_UA_NAME', 'ISR-CourseProject')}/0.1 "
        f"(+mailto:{os.getenv('ISR_CONTACT_EMAIL', 'isr-course@example.com')})"
    )

    n_ok = n_dl_fail = n_parse_fail = 0
    for url in tqdm(candidates, desc="docs"):
        pdf_bytes = download_pdf(url, ua)
        if pdf_bytes is None:
            n_dl_fail += 1
            time.sleep(args.delay)
            continue
        parsed = tika_extract(pdf_bytes, args.tika_url)
        if parsed is None or not parsed.text:
            n_parse_fail += 1
            time.sleep(args.delay)
            continue
        save_doc(col, snapshot_dir, url, pdf_bytes, parsed)
        n_ok += 1
        time.sleep(args.delay)

    logger.info(
        f"done: ok={n_ok} dl_fail={n_dl_fail} parse_fail={n_parse_fail} "
        f"total_attempted={len(candidates)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
