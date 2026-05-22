"""查询日志路由（对应作业 2.3.5）。

仅读取，写入由 search router 在每次查询时落入 query_log。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from api.deps import get_log_col

router = APIRouter(prefix="", tags=["log"])


@router.get("/logs")
def list_logs(
    user_id: str | None = Query(None, description="按用户过滤；空则返回全局最近 N 条"),
    limit: int = Query(50, ge=1, le=500),
    col: Any = Depends(get_log_col),
) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if user_id:
        query["user_id"] = user_id
    cursor = col.find(query, {"_id": 0}).sort("ts", -1).limit(limit)
    items = list(cursor)
    return {"count": len(items), "items": items}
