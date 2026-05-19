"""Wikipedia 爬虫：从给定 category 出发递归拉取条目。

Wikipedia 全量过大（~600 万英文条目），所以默认走 ``generator=categorymembers``
按种子分类深入；用户传 category 参数指定起点，例如 ``Fictional_characters``。

用法::

    scrapy crawl wiki -a lang=en -a category=Fictional_characters -a limit=10000
    scrapy crawl wiki -a lang=zh -a category=虚构角色 -a limit=10000
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable
from typing import Any

import scrapy
from scrapy.http import Response

from .mediawiki_base import MediaWikiBaseSpider


class WikiSpider(MediaWikiBaseSpider):
    name = "wiki"
    source = "wiki"

    # category 命名空间为 14，条目为 0；这里两者都要遍历
    cm_batch: int = 200
    cm_max_depth: int = 3

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

    async def start(self) -> AsyncIterator[scrapy.Request]:
        req = self._categorymembers_request(self.seed_category, depth=0)
        if req:
            yield req

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
