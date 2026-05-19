"""MediaWiki API 通用爬取基类。

Fandom 与 Wikipedia 都基于 MediaWiki，只是 API 入口与命名空间不同。
策略：
1. ``action=query&list=allpages`` 分页拿到全部主命名空间页面
2. 对每个 pageid 调 ``action=parse&prop=text|sections|links|categories``
   → 拿到完整 HTML、links（用作 anchors）、categories
3. 组装 ``PageItem`` 交给 pipeline
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable
from typing import Any
from urllib.parse import urlencode

import scrapy
from scrapy.http import Response

from ..items import PageItem
from ..utils import doc_id_for


class MediaWikiBaseSpider(scrapy.Spider):
    """子类需要设置 ``api_base``、``page_base``、``source``。"""

    api_base: str = ""
    page_base: str = ""
    source: str = ""

    # 默认抓主命名空间（普通条目）
    namespace: int = 0
    ap_batch: int = 200  # allpages 每页数量上限（默认 API 上限 500，保守用 200）

    def __init__(self, limit: int | str = 10000, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.limit = int(limit)
        self._yielded = 0

    # ------------------------------------------------------------------ #
    # 工具
    # ------------------------------------------------------------------ #

    def _api_request(self, params: dict[str, Any], callback, meta: dict[str, Any] | None = None):
        params = {"format": "json", "formatversion": "2", **params}
        url = f"{self.api_base}?{urlencode(params)}"
        return scrapy.Request(url=url, callback=callback, meta=meta or {})

    # ------------------------------------------------------------------ #
    # 入口
    # ------------------------------------------------------------------ #

    async def start(self) -> AsyncIterator[scrapy.Request]:
        yield self._allpages_request()

    def _allpages_request(self, apcontinue: str | None = None) -> scrapy.Request:
        params: dict[str, Any] = {
            "action": "query",
            "list": "allpages",
            "apnamespace": self.namespace,
            "aplimit": self.ap_batch,
            "apfilterredir": "nonredirects",
        }
        if apcontinue:
            params["apcontinue"] = apcontinue
        return self._api_request(params, callback=self.parse_allpages)

    def parse_allpages(self, response: Response) -> Iterable[scrapy.Request]:
        data = json.loads(response.text)
        pages = data.get("query", {}).get("allpages", [])

        for p in pages:
            if self._yielded >= self.limit:
                self.logger.info(f"达到 limit={self.limit}, 停止枚举")
                return
            self._yielded += 1
            yield self._parse_request(pageid=p["pageid"], title=p["title"])

        cont = data.get("continue", {}).get("apcontinue")
        if cont and self._yielded < self.limit:
            yield self._allpages_request(apcontinue=cont)

    def _parse_request(self, pageid: int, title: str) -> scrapy.Request:
        params = {
            "action": "parse",
            "pageid": pageid,
            "prop": "text|links|categories|sections|displaytitle|properties",
            "disableeditsection": "1",
        }
        return self._api_request(
            params,
            callback=self.parse_page,
            meta={"pageid": pageid, "title": title},
        )

    # ------------------------------------------------------------------ #
    # 单页解析
    # ------------------------------------------------------------------ #

    def parse_page(self, response: Response) -> Iterable[PageItem]:
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            self.logger.warning(f"非 JSON 响应: {response.url[:120]}")
            return

        parse = data.get("parse")
        if not parse:
            self.logger.debug(f"无 parse 字段: {response.meta.get('title')}")
            return

        # MediaWiki API 保证 parse.title 为纯文本；displaytitle 可能含 HTML 装饰，仅供展示
        plain_title = parse.get("title") or response.meta.get("title", "")
        display_title = parse.get("displaytitle") or plain_title
        html = parse.get("text", "") or ""
        url = self._build_page_url(plain_title)
        categories = [c.get("category", "") for c in parse.get("categories", []) if c.get("category")]

        item = PageItem()
        item["doc_id"] = doc_id_for(url)
        item["source"] = self.source
        item["url"] = url
        item["title"] = self._strip_html(display_title)
        item["raw_html"] = html
        item["tag"] = self.classify_tag(categories)
        item["extra"] = {
            "categories": categories,
            "pageid": response.meta.get("pageid"),
            "sections": [s.get("line") for s in parse.get("sections", [])],
        }
        yield item

    # ------------------------------------------------------------------ #
    # 钩子（子类可覆盖）
    # ------------------------------------------------------------------ #

    def _build_page_url(self, title: str) -> str:
        return f"{self.page_base}{title.replace(' ', '_')}"

    @staticmethod
    def _strip_html(s: str) -> str:
        if "<" not in s:
            return s
        from bs4 import BeautifulSoup

        return BeautifulSoup(s, "lxml").get_text(strip=True)

    def classify_tag(self, categories: list[str]) -> str:
        """粗分类：默认为 canon。子类可基于分类名扩展。"""
        return "canon"
