"""Wikipedia 爬虫：从给定 category 出发递归拉取条目。

Wikipedia 全量过大（~600 万英文条目），所以默认走 ``generator=categorymembers``
按种子分类深入；用户传 category 参数指定起点，例如 ``Fictional_characters``。

特别说明（与 Fandom 不同）：
- Wikipedia 的 ``robots.txt`` 含 ``Disallow: /w/``，会阻断 ``/w/api.php`` 上的 API 调用。
  但 mediawiki.org/wiki/API:Etiquette 明确允许 API 用户**不受 robots.txt 约束**，
  只要 (a) UA 带联系方式、(b) 限速保守、(c) 不并发轰炸。
  因此 ``custom_settings`` 里关掉 ``ROBOTSTXT_OBEY``，并把速率压到 2 req/s。

- 若 ``.env`` 提供 ``WIKI_USERNAME / WIKI_BOT_PASSWORD``（Bot Password），
  spider 在抓取前先走 ``action=login`` 流程；cookies 由 CookiesMiddleware 自动维持。

用法::

    scrapy crawl wiki -a lang=en -a category=Fictional_characters -a limit=10000
    scrapy crawl wiki -a lang=zh -a category=虚构角色 -a limit=10000
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Iterable
from typing import Any

import scrapy
from scrapy.http import FormRequest, Response

from .mediawiki_base import MediaWikiBaseSpider


class WikiSpider(MediaWikiBaseSpider):
    name = "wiki"
    source = "wiki"

    # category 命名空间为 14，条目为 0；这里两者都要遍历
    cm_batch: int = 200
    cm_max_depth: int = 3

    # 仅对 wiki spider 生效：关 robots（API 用户豁免）+ 2 req/s 节流
    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "CONCURRENT_REQUESTS": 2,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_DELAY": 0.5,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 0.5,
        "AUTOTHROTTLE_MAX_DELAY": 5.0,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 1.0,
    }

    def __init__(
        self,
        lang: str = "en",
        category: str = "Fictional_characters",
        limit: int | str = 10000,
        max_depth: int | str = 3,
        **kwargs: Any,
    ) -> None:
        super().__init__(limit=limit, **kwargs)
        self.lang = lang
        self.seed_category = category
        self.cm_max_depth = int(max_depth)
        host = f"{lang}.wikipedia.org"
        self.api_base = f"https://{host}/w/api.php"
        self.page_base = f"https://{host}/wiki/"
        self.allowed_domains = [host]
        self._visited_categories: set[str] = set()
        self._logged_in = False

    # ------------------------------------------------------------------ #
    # 入口：可选先登录
    # ------------------------------------------------------------------ #

    async def start(self) -> AsyncIterator[scrapy.Request]:
        username = os.getenv("WIKI_USERNAME") or ""
        password = os.getenv("WIKI_BOT_PASSWORD") or ""
        if username and password:
            self.logger.info(f"[wiki] using bot login as {username}")
            yield self._login_token_request()
        else:
            self.logger.info("[wiki] anonymous mode (no WIKI_USERNAME / WIKI_BOT_PASSWORD)")
            req = self._categorymembers_request(self.seed_category, depth=0)
            if req:
                yield req

    def _login_token_request(self) -> scrapy.Request:
        params = {"action": "query", "meta": "tokens", "type": "login"}
        return self._api_request(params, callback=self._on_login_token)

    def _on_login_token(self, response: Response) -> Iterable[scrapy.Request]:
        data = json.loads(response.text)
        token = data.get("query", {}).get("tokens", {}).get("logintoken")
        if not token:
            self.logger.error(f"[wiki] cannot obtain logintoken: {data}")
            return
        yield FormRequest(
            url=self.api_base,
            formdata={
                "action": "login",
                "lgname": os.environ["WIKI_USERNAME"],
                "lgpassword": os.environ["WIKI_BOT_PASSWORD"],
                "lgtoken": token,
                "format": "json",
                "formatversion": "2",
            },
            callback=self._on_login,
            dont_filter=True,
        )

    def _on_login(self, response: Response) -> Iterable[scrapy.Request]:
        data = json.loads(response.text)
        result = data.get("login", {}).get("result")
        if result == "Success":
            who = data["login"].get("lgusername", "")
            self.logger.info(f"[wiki] login OK as {who}")
            self._logged_in = True
            req = self._categorymembers_request(self.seed_category, depth=0)
            if req:
                yield req
        else:
            # 登录失败：明确日志后由 Scrapy 自然关闭
            self.logger.error(f"[wiki] login FAILED: {data}")

    # ------------------------------------------------------------------ #
    # 分类遍历
    # ------------------------------------------------------------------ #

    def _categorymembers_request(
        self,
        category: str,
        depth: int,
        cmcontinue: str | None = None,
    ) -> scrapy.Request:
        if category in self._visited_categories:
            return None  # type: ignore[return-value]
        self._visited_categories.add(category)
        params: dict[str, Any] = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{category}",
            "cmlimit": self.cm_batch,
            "cmtype": "page|subcat",
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue
        return self._api_request(
            params,
            callback=self.parse_categorymembers,
            meta={"category": category, "depth": depth},
        )

    def parse_categorymembers(self, response: Response) -> Iterable[scrapy.Request]:
        data = json.loads(response.text)
        members = data.get("query", {}).get("categorymembers", [])
        depth: int = response.meta["depth"]
        category: str = response.meta["category"]

        for m in members:
            ns = m.get("ns")
            if self._yielded >= self.limit:
                return
            if ns == 0:  # 条目
                self._yielded += 1
                yield self._parse_request(pageid=m["pageid"], title=m["title"])
            elif ns == 14 and depth < self.cm_max_depth:  # 子分类
                sub = m["title"].removeprefix("Category:")
                req = self._categorymembers_request(sub, depth=depth + 1)
                if req:
                    yield req

        cont = data.get("continue", {}).get("cmcontinue")
        if cont and self._yielded < self.limit:
            yield self._categorymembers_request(category, depth, cmcontinue=cont)

    def classify_tag(self, categories: list[str]) -> str:
        """Wikipedia 条目默认权威，统一标为 canon。"""
        return "canon"
