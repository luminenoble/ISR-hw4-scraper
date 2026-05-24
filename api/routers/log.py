"""查询日志路由（对应作业 2.3.5）。

仅读取，写入由 search router 在每次查询时落入 query_log。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from api.deps import get_current_user_required, get_log_col

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


@router.get("/logs/me")
def my_logs(
    user: Annotated[dict, Depends(get_current_user_required)],
    limit: int = Query(50, ge=1, le=500),
    col: Any = Depends(get_log_col),
) -> dict[str, Any]:
    """当前登录用户的搜索历史，按时间倒序。"""
    cursor = col.find({"user_id": user["user_id"]}, {"_id": 0}).sort("ts", -1).limit(limit)
    items = list(cursor)
    return {"count": len(items), "items": items}


@router.get("/logs/clicks/me")
def my_clicks(
    user: Annotated[dict, Depends(get_current_user_required)],
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """当前用户的点击历史（来自 users.click_history，已按时间累积）。"""
    history = list(user.get("click_history") or [])
    history.reverse()  # 末尾最新 → 头部最新
    return {"count": min(len(history), limit), "items": history[:limit]}
