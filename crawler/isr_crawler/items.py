"""Scrapy Item 定义，对齐 design.md §3.1 的统一 schema。"""

from __future__ import annotations

import scrapy


class PageItem(scrapy.Item):
    doc_id = scrapy.Field()
    source = scrapy.Field()
    url = scrapy.Field()
    title = scrapy.Field()
    character_name = scrapy.Field()
    infobox = scrapy.Field()
    body_text = scrapy.Field()
    raw_html = scrapy.Field()
    anchors = scrapy.Field()
    tag = scrapy.Field()
    popularity = scrapy.Field()
    fetched_at = scrapy.Field()
    snapshot_path = scrapy.Field()
    extra = scrapy.Field()
