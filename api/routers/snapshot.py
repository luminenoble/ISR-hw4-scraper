"""网页快照路由（对应作业 2.3.6）。

从 Mongo 取 ``snapshot_path``（项目根相对路径） → 读 gzip → 按扩展名设 MIME 返回。
"""

from __future__ import annotations

import gzip
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from api.deps import SNAPSHOT_BASE, get_pages_col

router = APIRouter(prefix="", tags=["snapshot"])


def _mime_for(rel_path: str) -> str:
    if rel_path.endswith(".pdf.gz"):
        return "application/pdf"
    return "text/html; charset=utf-8"


@router.get("/snapshot/{doc_id}")
def snapshot(doc_id: str, col: Any = Depends(get_pages_col)) -> Response:
    doc = col.find_one({"doc_id": doc_id}, {"snapshot_path": 1, "url": 1})
    if not doc or not doc.get("snapshot_path"):
        raise HTTPException(status_code=404, detail="snapshot not found")

    rel = doc["snapshot_path"]
    full = SNAPSHOT_BASE / rel
    if not full.exists():
        raise HTTPException(status_code=410, detail="snapshot file missing on disk")

    with gzip.open(full, "rb") as f:
        body = f.read()

    return Response(
        content=body,
        media_type=_mime_for(rel),
        headers={
            "X-Snapshot-Url": doc.get("url") or "",
            "Cache-Control": "public, max-age=3600",
        },
    )
