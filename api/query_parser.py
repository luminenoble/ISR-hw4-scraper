"""查询字符串解析：识别短语 / 通配 / 字段前缀过滤。

对应 design.md §3.4 中 6 种查询的 "kind 分流"：

- 含引号 ``"..."``：phrase 查询（match_phrase）
- 含 ``*`` 或 ``?``：wildcard 查询
- 否则：默认 multi_match
- 前缀 ``site:fandom`` / ``source:document`` / ``tag:canon``：转 filter term，从查询体中剥离

输出 ``ParsedQuery``，由 search router 决定如何拼 ES DSL。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 前缀过滤的字段白名单（防止用户写 site:xxx 后被任意字段过滤）
_FILTER_KEYS = {"site", "source", "tag"}
# 通配符号
_WILDCARD_RE = re.compile(r"[*?]")
# "..." 短语：支持中英文引号
_PHRASE_RE = re.compile(r'["“]([^"”]+)["”]')
# field:value 前缀过滤（value 可含字母数字_-）
_FILTER_RE = re.compile(r"\b([a-z_]+):([A-Za-z0-9_.\-]+)")


@dataclass
class ParsedQuery:
    """查询解析结果。

    Attributes:
        raw: 原始字符串
        terms: 剥离短语 / 通配 / 过滤后剩下的关键词（空格分隔）
        phrases: 双引号内的短语列表
        filters: 字段过滤 {字段名: 值}；site 会被规范化到 source
        wildcard: 含通配符时保留原始 token（含 * ?）
        kind: "phrase" / "wildcard" / "match"
    """

    raw: str
    terms: str = ""
    phrases: list[str] = field(default_factory=list)
    filters: dict[str, str] = field(default_factory=dict)
    wildcard: str | None = None
    kind: str = "match"


def parse(q: str) -> ParsedQuery:
    """解析查询字符串。空串返回空 ParsedQuery（kind=match）。

    优先级：先抽过滤前缀 → 抽短语 → 判通配 → 剩余即关键词。
    """
    pq = ParsedQuery(raw=q or "")
    if not q:
        return pq

    s = q.strip()

    # 1. 字段过滤前缀 —— 先 site/source/tag 这种 key:val 全部抠走
    for m in _FILTER_RE.finditer(s):
        key, val = m.group(1).lower(), m.group(2)
        if key in _FILTER_KEYS:
            # site 是 source 的常见别名（site:fandom 等同 source:fandom）
            if key == "site":
                key = "source"
            pq.filters[key] = val
    s = _FILTER_RE.sub("", s).strip()

    # 2. 引号短语
    for m in _PHRASE_RE.finditer(s):
        ph = m.group(1).strip()
        if ph:
            pq.phrases.append(ph)
    s = _PHRASE_RE.sub("", s).strip()

    # 3. 残余 token 判断是否含通配
    s = re.sub(r"\s+", " ", s).strip()
    if _WILDCARD_RE.search(s):
        pq.wildcard = s
        pq.kind = "wildcard"
    elif pq.phrases:
        pq.kind = "phrase"
        pq.terms = s
    else:
        pq.terms = s
        pq.kind = "match"

    return pq
