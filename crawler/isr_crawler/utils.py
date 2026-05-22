"""通用工具：doc_id、快照路径、HTML 清洗、时间戳。"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

from bs4 import BeautifulSoup

_WS_RE = re.compile(r"\s+")


def doc_id_for(url: str) -> str:
    """对 URL 取 sha1 作为统一文档 ID。"""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def now_iso_utc() -> str:
    """ISO 8601 UTC 时间戳（秒精度，带 Z 后缀）。"""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def snapshot_path_for(
    doc_id: str, base_dir: str | Path, ext: str = "html.gz"
) -> Path:
    """两级分桶 `ab/cd/<doc_id>.<ext>`，避免单目录文件过多。

    ``ext`` 用于区分网页快照（``html.gz``）与文档源（如 ``pdf.gz``）。
    """
    base = Path(base_dir)
    return base / doc_id[:2] / doc_id[2:4] / f"{doc_id}.{ext}"


def clean_text(html_or_text: str) -> str:
    """提取 HTML 纯文本并压缩空白；输入若已是文本也安全。"""
    if not html_or_text:
        return ""
    soup = BeautifulSoup(html_or_text, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return _WS_RE.sub(" ", text).strip()


def extract_anchors(html: str, base_url: str | None = None) -> list[dict[str, str]]:
    """从 HTML 中抽取 ``<a>`` 锚文本与目标，过滤空文本与无效链接。"""
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    out: list[dict[str, str]] = []
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        text = (a.get_text() or "").strip()
        if not href or not text or href.startswith("#"):
            continue
        out.append({"text": text, "to": href})
    return out
