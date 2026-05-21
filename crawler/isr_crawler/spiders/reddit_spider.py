"""Reddit 爬虫：通过 arctic-shift 镜像 API 拉取 submissions。

为什么不用 PRAW：
- Reddit 官方 API 已在 2024 年加入 Responsible Builder Policy，新账号注册申请门槛高
- arctic-shift 是 Pushshift 关停后的社区接续，公开免凭据，历史深度更友好
- 课程作业需要的是"民间二创讨论"语料，历史数据比实时数据价值更高

API：``https://arctic-shift.photon-reddit.com/api/posts/search``

用法::

    # 跑 5 个同人写作 subreddit，每个上限分摊到 10000 总量
    scrapy crawl reddit -a subreddits=HPfanfiction,FanFiction,AO3,CharacterRant,fanfiction -a limit=10000

    # 限定时间窗（防止拉到太老的 post）
    scrapy crawl reddit -a subreddits=onepiece -a after=2023-01-01 -a limit=5000
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Iterable
from typing import Any
from urllib.parse import urlencode

import scrapy
from scrapy.http import Response

from ..items import PageItem
from ..utils import doc_id_for


class RedditSpider(scrapy.Spider):
    name = "reddit"
    source = "reddit"

    # arctic-shift 文档建议"几次每秒"不需要担心；这里保守按 2 req/s
    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "CONCURRENT_REQUESTS": 2,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_DELAY": 0.5,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 1.0,
        "AUTOTHROTTLE_MAX_DELAY": 10.0,
    }

    DEFAULT_SUBREDDITS = (
        "HPfanfiction,FanFiction,AO3,CharacterRant,fanfiction,"
        "onepiece,genshin_impact,HazbinHotel,HelluvaBoss"
    )

    def __init__(
        self,
        subreddits: str = DEFAULT_SUBREDDITS,
        limit: int | str = 10000,
        before: str | None = None,
        after: str | None = None,
        api_base: str | None = None,
        **kwargs: Any,
    ) -> None:
        """初始化 Reddit spider。

        Args:
            subreddits: 逗号分隔的 subreddit 名字列表（不带 r/ 前缀）
            limit: 全局 item 上限（跨 subreddit 汇总）
            before: 仅抓取 ``created_utc < before`` 的 post，ISO 日期或 unix 秒
            after: 仅抓取 ``created_utc > after`` 的 post
            api_base: 覆盖 arctic-shift API 根；默认走环境变量 ``ARCTIC_SHIFT_BASE``
        """
        super().__init__(**kwargs)
        self.subreddits = [s.strip() for s in subreddits.split(",") if s.strip()]
        self.limit = int(limit)
        self.before = before
        self.after = after
        self.api_base = (
            api_base
            or os.getenv("ARCTIC_SHIFT_BASE")
            or "https://arctic-shift.photon-reddit.com"
        )
        self.api_endpoint = "/api/posts/search"
        self.allowed_domains = ["arctic-shift.photon-reddit.com"]
        self._yielded = 0

    # ------------------------------------------------------------------ #
    # 入口
    # ------------------------------------------------------------------ #

    async def start(self) -> AsyncIterator[scrapy.Request]:
        if not self.subreddits:
            self.logger.error("no subreddits given")
            return
        self.logger.info(
            f"[reddit] subreddits={self.subreddits} limit={self.limit} "
            f"before={self.before} after={self.after}"
        )
        for sub in self.subreddits:
            yield self._search_request(sub, before=self.before)

    def _search_request(
        self,
        subreddit: str,
        before: str | None = None,
    ) -> scrapy.Request:
        params: dict[str, Any] = {
            "subreddit": subreddit,
            "limit": 100,
            "sort": "desc",  # 新→旧
        }
        if before is not None:
            params["before"] = str(before)
        if self.after is not None:
            params["after"] = str(self.after)
        url = self.api_base + self.api_endpoint + "?" + urlencode(params)
        return scrapy.Request(
            url=url,
            callback=self.parse_search,
            meta={"subreddit": subreddit},
        )

    # ------------------------------------------------------------------ #
    # 解析与分页
    # ------------------------------------------------------------------ #

    def parse_search(self, response: Response) -> Iterable[scrapy.Request | PageItem]:
        sub: str = response.meta["subreddit"]
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            self.logger.warning(f"[reddit] non-JSON response from {response.url[:160]}")
            return

        posts = data.get("data", [])
        if not posts:
            self.logger.info(f"[reddit] r/{sub}: empty page, stopping this branch")
            return

        oldest_ts: int | None = None
        for post in posts:
            if self._yielded >= self.limit:
                return
            ts = post.get("created_utc")
            if isinstance(ts, int | float):
                oldest_ts = int(ts) if oldest_ts is None else min(oldest_ts, int(ts))
            self._yielded += 1
            item = self._item_from_post(post)
            if item is not None:
                yield item

        # 翻页：用本批最旧的 created_utc 作为下一页的 before
        if oldest_ts and self._yielded < self.limit:
            yield self._search_request(sub, before=oldest_ts)

    # ------------------------------------------------------------------ #
    # Submission → PageItem
    # ------------------------------------------------------------------ #

    def _item_from_post(self, post: dict[str, Any]) -> PageItem | None:
        pid = post.get("id")
        subreddit = post.get("subreddit") or ""
        permalink = post.get("permalink") or (
            f"/r/{subreddit}/comments/{pid}/" if pid else None
        )
        if not permalink:
            return None
        url = f"https://www.reddit.com{permalink}"

        title = (post.get("title") or "").strip()
        selftext = post.get("selftext") or ""
        selftext_html = post.get("selftext_html") or ""
        author = post.get("author") or "[deleted]"
        flair = post.get("link_flair_text") or ""
        score = post.get("score", 0) or 0
        num_comments = post.get("num_comments", 0) or 0

        # 构造快照 HTML：优先用 reddit 自带渲染的 selftext_html
        if selftext_html:
            body_html = selftext_html
        elif selftext:
            body_html = f"<pre>{selftext}</pre>"
        else:
            body_html = ""

        raw_html = (
            f"<html><head><title>{title}</title></head><body>"
            f"<h1>{title}</h1>"
            f"<p>By u/{author} in r/{subreddit} | "
            f"Score: {score} | Comments: {num_comments} | Flair: {flair}</p>"
            f'<div class="selftext">{body_html}</div>'
            f"</body></html>"
        )

        item = PageItem()
        item["doc_id"] = doc_id_for(url)
        item["source"] = "reddit"
        item["url"] = url
        item["title"] = title
        item["raw_html"] = raw_html
        # selftext 已是纯文本；直接喂给 body_text 避免 CleanPipeline 把头部 boilerplate 也算进正文
        item["body_text"] = selftext
        item["popularity"] = float(score) if isinstance(score, int | float) else 0.0
        item["tag"] = self._classify_tag(flair)
        item["extra"] = {
            "subreddit": subreddit,
            "author": author,
            "created_utc": post.get("created_utc"),
            "num_comments": num_comments,
            "link_flair_text": flair,
            "post_id": pid,
            "over_18": bool(post.get("over_18", False)),
        }
        return item

    # ------------------------------------------------------------------ #
    # Tag 启发
    # ------------------------------------------------------------------ #

    @staticmethod
    def _classify_tag(flair: str) -> str:
        f = (flair or "").lower()
        if "canon" in f:
            return "canon"
        if "crossover" in f:
            return "crossover"
        if any(k in f for k in ("meta", "discussion", "rant", "question", "help")):
            return "meta"
        if any(k in f for k in ("fanon", "fanfic", "story", "self-promotion", "promo")):
            return "fanon"
        # Reddit 子版默认偏二创讨论
        return "fanon"
