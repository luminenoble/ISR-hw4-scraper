"""AO3 spider：仅抓列表页 summary + 元数据，不进 detail 页。

策略（design.md §3.1 ao3 行 + sec9 决策）：

- 入口 ``/tags/<canonical_tag>/works`` 列表页，每页 20 条 `<li class="work blurb group">`
- 列表页本身已包含 summary / rating / warnings / tags / kudos / bookmarks / hits 等所有需要的字段
- 不进 detail 页 → 请求数 = pages，与 reddit/wiki 同量级
- 默认 2 req/s（DOWNLOAD_DELAY=0.5）+ AUTOTHROTTLE，AO3 实测足够安全
- ``view_adult=true`` cookie 主动放上，避免 M 内容跳转挑战页

CLI::

    # 默认抓 Genshin Impact 前 2500 页（约 50000 条，按 kudos 倒序）
    scrapy crawl ao3

    # 自定义 tag / 页数 / 排序
    scrapy crawl ao3 -a tag="Honkai: Star Rail" -a max_pages=200 -a sort=hits_count

    # 冒烟（只抓 2 页）
    scrapy crawl ao3 -a max_pages=2

去重：跨页同 doc_id 由 Mongo upsert 兜底；page 5000 后 AO3 返回空，spider 自然停。
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterable
from typing import Any
from urllib.parse import quote, urlencode

import scrapy
from scrapy.http import Response

from ..items import PageItem
from ..utils import doc_id_for, now_iso_utc

_BASE = "https://archiveofourown.org"
# AO3 canonical Genshin tag（中英合并 wrangler 已经做了）
_DEFAULT_TAG = "原神 | Genshin Impact (Video Game)"
# 一页 20 条；翻页参数 page=N
_DIGIT_RE = re.compile(r"[\d,]+")


def _to_int(s: str | None) -> int:
    """AO3 数字带逗号（'9,125'）；非数字回 0。"""
    if not s:
        return 0
    m = _DIGIT_RE.search(s)
    if not m:
        return 0
    return int(m.group(0).replace(",", ""))


def _classify_tag(freeforms: list[str], relationships: list[str]) -> str:
    """从 freeform / relationship tag 推断 canon/fanon/crossover/meta。

    粗规则：
        - 含 "Alternate Universe" / "AU" / "OC" / "Self-Insert" → fanon
        - 含 "Crossover" / "Fusion" 关键词 → crossover
        - 含 "Meta" / "Essay" → meta
        - 其余且 relationship 为 canonical pairing → canon
    """
    joined = " | ".join(freeforms).lower()
    if any(k in joined for k in ("alternate universe", " au", "oc ", "self-insert", "self insert")):
        return "fanon"
    if any(k in joined for k in ("crossover", "fusion")):
        return "crossover"
    if any(k in joined for k in ("meta", "essay", "analysis")):
        return "meta"
    return "canon"


def parse_work_blurb(li, source_url: str) -> dict[str, Any] | None:
    """解析单个 `<li class="work blurb group">` 节点为 PageItem 字段字典。

    返回 None 表示 skip（缺标题 / 缺 url）。lxml/beautifulsoup 节点类型不在签名标注，
    便于单测 mock。
    """
    # ---- url / title / author ----
    heading_a = li.select_one(".heading a[href^='/works/']")
    if heading_a is None:
        return None
    href = heading_a.get("href") or ""
    if not href.startswith("/works/"):
        return None
    title = heading_a.get_text(strip=True)
    if not title:
        return None
    work_id_match = re.search(r"/works/(\d+)", href)
    work_id = work_id_match.group(1) if work_id_match else None
    url = _BASE + href.split("?", 1)[0]

    author_a = li.select_one(".heading a[rel='author']")
    author = author_a.get_text(strip=True) if author_a else "Anonymous"

    # ---- required-tags 区：rating / warnings / category / WIP ----
    rating = ""
    rating_span = li.select_one("span.rating .text")
    if rating_span:
        rating = rating_span.get_text(strip=True)

    warnings_text: list[str] = []
    for s in li.select("span.warnings .text"):
        t = s.get_text(strip=True)
        if t:
            warnings_text.append(t)

    is_wip = li.select_one("span.complete-no.iswip") is not None

    # ---- 标签群：fandom / relationship / character / freeform ----
    fandom = [a.get_text(strip=True) for a in li.select("li.fandoms a.tag")]
    relationship = [a.get_text(strip=True) for a in li.select("li.relationships a.tag")]
    character = [a.get_text(strip=True) for a in li.select("li.characters a.tag")]
    freeform = [a.get_text(strip=True) for a in li.select("li.freeforms a.tag")]

    # ---- summary ----
    summary_el = li.select_one("blockquote.userstuff.summary")
    if summary_el is not None:
        # 多 <p> 合并，保留段落隔行；AO3 summary 上限 1250 字符
        paras = [p.get_text(" ", strip=True) for p in summary_el.find_all("p")]
        if paras:
            summary = "\n\n".join(paras)
        else:
            summary = summary_el.get_text(" ", strip=True)
    else:
        summary = ""

    # ---- stats ----
    stats = li.select_one("dl.stats")
    language = ""
    word_count = 0
    chapters_done = 0
    chapters_total: int | None = None
    kudos = bookmarks = hits = 0
    if stats is not None:
        for dt in stats.find_all("dt"):
            cls = " ".join(dt.get("class") or [])
            dd = dt.find_next_sibling("dd")
            if dd is None:
                continue
            txt = dd.get_text(" ", strip=True)
            if cls == "language":
                language = txt
            elif cls == "words":
                word_count = _to_int(txt)
            elif cls == "chapters":
                # "4/10" or "1/1" or "5/?"
                parts = txt.split("/")
                chapters_done = _to_int(parts[0]) if parts else 0
                if len(parts) > 1:
                    rest = parts[1].strip()
                    chapters_total = None if rest == "?" else _to_int(rest)
            elif cls == "kudos":
                kudos = _to_int(txt)
            elif cls == "bookmarks":
                bookmarks = _to_int(txt)
            elif cls == "hits":
                hits = _to_int(txt)

    datetime_el = li.select_one(".datetime")
    updated_at = datetime_el.get_text(strip=True) if datetime_el else ""

    # ---- popularity 组合：log1p(kudos)·0.6 + log1p(bookmarks)·0.3 + log1p(hits)·0.1 ----
    import math

    popularity = (
        math.log1p(kudos) * 0.6
        + math.log1p(bookmarks) * 0.3
        + math.log1p(hits) * 0.1
    )

    return {
        "url": url,
        "title": title,
        "author": author,
        "work_id": work_id,
        "is_wip": is_wip,
        "rating": rating,
        "warnings": warnings_text,
        "fandom": fandom,
        "relationship": relationship,
        "character": character,
        "freeform": freeform,
        "summary": summary,
        "language": language,
        "word_count": word_count,
        "chapters_completed": chapters_done,
        "chapters_total": chapters_total,
        "kudos": kudos,
        "bookmarks": bookmarks,
        "hits": hits,
        "updated_at": updated_at,
        "popularity": popularity,
        "tag": _classify_tag(freeform, relationship),
        "source_url": source_url,
    }


class AO3Spider(scrapy.Spider):
    name = "ao3"
    source = "ao3"

    # AO3 单页响应 ~15s（WSL → AO3 国际链路慢），靠 fan-out 多并发拉满 ~2 req/s
    # 4 并发 × 0.5s 间隔，正好对齐用户要求的 2 req/s 上限；autothrottle 关掉避免被
    # 高 latency 误判后掉到 < 1 req/min
    custom_settings = {
        "ROBOTSTXT_OBEY": True,
        "CONCURRENT_REQUESTS": 4,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 4,
        "DOWNLOAD_DELAY": 0.5,
        "AUTOTHROTTLE_ENABLED": False,
        "HTTPCACHE_ENABLED": False,
        "COOKIES_ENABLED": True,
        "DOWNLOAD_TIMEOUT": 60,
        # AO3 经过 Cloudflare，偶发 520/525 都是上游握手失败，重试通常即解决
        "RETRY_HTTP_CODES": [429, 500, 502, 503, 504, 520, 521, 522, 524, 525, 408],
        "RETRY_TIMES": 5,
    }

    def __init__(
        self,
        tag: str = _DEFAULT_TAG,
        max_pages: int | str = 2500,
        sort: str = "kudos_count",
        limit: int | str | None = None,
        **kwargs: Any,
    ) -> None:
        """初始化 AO3 spider。

        Args:
            tag: AO3 canonical tag 名（不含 URL 编码）。默认 Genshin Impact
            max_pages: 翻页上限；AO3 单 tag 最深 page=5000
            sort: 排序列：``kudos_count`` / ``hits`` / ``bookmarks_count`` / ``revised_at`` / ``word_count``
            limit: item 上限（跨页累计）；None 表示不限
        """
        super().__init__(**kwargs)
        self.tag = tag
        self.max_pages = int(max_pages)
        self.sort = sort
        self.limit: int | None = int(limit) if limit is not None else None
        self.allowed_domains = ["archiveofourown.org"]
        self._yielded = 0

    async def start(self) -> AsyncIterator[scrapy.Request]:
        """fan-out：一次性把全部 page 请求挂入调度器。

        AO3 单页慢（WSL 出海 ~15s），靠 ``CONCURRENT_REQUESTS_PER_DOMAIN=4`` 把
        多 page 同时在飞，整体吞吐 ≈ 2 req/s。
        ``parse_listing`` 不再自己挂 next_page，避免重复入队。
        """
        self.logger.info(
            f"[ao3] tag={self.tag!r} sort={self.sort} "
            f"max_pages={self.max_pages} limit={self.limit} (fan-out mode)"
        )
        for page in range(1, self.max_pages + 1):
            yield self._listing_request(page)

    def _listing_request(self, page: int) -> scrapy.Request:
        # tag 用 quote(safe='') 全部转义，避免空格 / 中文 / | 等字符出错
        encoded_tag = quote(self.tag, safe="")
        qs = urlencode(
            {
                "work_search[sort_column]": self.sort,
                "view_adult": "true",
                "page": page,
            }
        )
        url = f"{_BASE}/tags/{encoded_tag}/works?{qs}"
        return scrapy.Request(
            url=url,
            callback=self.parse_listing,
            meta={"page": page},
            # 主动塞 view_adult cookie 防止重定向
            cookies={"view_adult": "true"},
        )

    def parse_listing(self, response: Response) -> Iterable[scrapy.Request | PageItem]:
        page: int = response.meta["page"]
        works = response.css("li.work.blurb.group")
        if not works:
            # AO3 翻到没结果的页就返回空 ul；fan-out 模式下后续页同样可能空，不停整个 spider
            self.logger.debug(f"[ao3] empty page {page}")
            # 用 break 出空循环代替 return：让 Scrapy 的 AST 启发式（is_generator_with_return_value）
            # 不会在任何 Python 版本上误报"return with value"
            blurbs: list = []
        else:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, "lxml")
            blurbs = soup.select("li.work.blurb.group")

        for blurb in blurbs:
            if self.limit is not None and self._yielded >= self.limit:
                break
            parsed = parse_work_blurb(blurb, source_url=response.url)
            if parsed is None:
                continue
            self._yielded += 1
            yield self._item_from_parsed(parsed)

    def _item_from_parsed(self, p: dict[str, Any]) -> PageItem:
        """parsed dict → PageItem。AO3 专属字段塞 extra，便于 build_index 提升到 ES。"""
        url = p["url"]
        # body_text 用 summary：列表页里这是最重要的"作品介绍"
        # title + tag 文本 join 一并塞 body，让 BM25 多字段命中更稳
        title = p["title"]
        summary = p["summary"]
        body_text = summary or title

        # 不存网页快照：列表页 5KB × 50k = 250MB 不值得，且单作品的 summary 已存在 body
        item = PageItem()
        item["doc_id"] = doc_id_for(url)
        item["source"] = "ao3"
        item["url"] = url
        item["title"] = title
        item["body_text"] = body_text
        item["raw_html"] = None  # 不存快照
        item["popularity"] = float(p["popularity"])
        item["tag"] = p["tag"]
        item["fetched_at"] = now_iso_utc()
        item["anchors"] = []
        item["character_name"] = (p["character"][0] if p["character"] else None)
        item["infobox"] = {}
        item["extra"] = {
            "author": p["author"],
            "work_id": p["work_id"],
            "rating": p["rating"],
            "warnings": p["warnings"],
            "is_wip": p["is_wip"],
            "ao3_tags": {
                "fandom": p["fandom"],
                "relationship": p["relationship"],
                "character": p["character"],
                "freeform": p["freeform"],
            },
            "language": p["language"],
            "word_count": p["word_count"],
            "chapters_completed": p["chapters_completed"],
            "chapters_total": p["chapters_total"],
            "kudos": p["kudos"],
            "bookmarks": p["bookmarks"],
            "hits": p["hits"],
            "updated_at": p["updated_at"],
            "source_listing_url": p["source_url"],
        }
        return item
