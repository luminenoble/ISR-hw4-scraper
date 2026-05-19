"""Fandom 爬虫：通过 MediaWiki API 拉取某个 wiki 的全部主命名空间条目。

用法::

    scrapy crawl fandom -a wiki=onepiece -a lang=en -a limit=10000

参数:
    wiki: 子域，如 onepiece / genshin-impact / hetalia
    lang: 语种前缀，en 默认；中文 zh
    limit: 最大抓取条数
"""

from __future__ import annotations

from typing import Any

from .mediawiki_base import MediaWikiBaseSpider


class FandomSpider(MediaWikiBaseSpider):
    name = "fandom"
    source = "fandom"

    def __init__(
        self,
        wiki: str = "onepiece",
        lang: str = "en",
        limit: int | str = 10000,
        **kwargs: Any,
    ) -> None:
        super().__init__(limit=limit, **kwargs)
        self.wiki = wiki
        self.lang = lang
        host = f"{wiki}.fandom.com"
        prefix = "" if lang == "en" else f"{lang}/"
        self.api_base = f"https://{host}/{prefix}api.php"
        self.page_base = f"https://{host}/{prefix}wiki/"
        self.allowed_domains = [host]

    def classify_tag(self, categories: list[str]) -> str:
        """根据 Fandom 分类名给 tag 打标签。"""
        joined = " ".join(c.lower() for c in categories)
        if "fanon" in joined or "fan fiction" in joined or "fanfiction" in joined:
            return "fanon"
        if "crossover" in joined:
            return "crossover"
        if "meta" in joined or "real world" in joined:
            return "meta"
        return "canon"
