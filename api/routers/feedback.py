"""隐式反馈：点击事件 → 更新用户档案。

POST /feedback/click  body={doc_id, query?, dwell_ms?}
- 必须登录
- 通过 doc_id 查 ES 拿 source/tag（缺失时只更新 click_doc_ids/history）
- 调 personalization.apply_click_update 算增量，落 Mongo
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger

from api.deps import INDEX_NAME, get_current_user_required, get_es, get_users_col
from api.personalization import apply_click_update
from api.routers.auth import _to_profile
from api.schemas import ClickRequest, UserProfile

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("/click", response_model=UserProfile)
def click(
    req: ClickRequest,
    user: Annotated[dict, Depends(get_current_user_required)],
    es=Depends(get_es),
    users=Depends(get_users_col),
) -> UserProfile:
    # 拉 doc 的 source / tag 供权重 bump 使用；doc 不存在不算错（仅维护点击集）
    source: str | None = None
    tag: str | None = None
    try:
        resp = es.get(index=INDEX_NAME, id=req.doc_id, _source=["source", "tag"])
        src = resp.get("_source") or {}
        source = src.get("source")
        tag = src.get("tag")
    except Exception as e:
        logger.debug(f"click: ES doc {req.doc_id} not found ({e}); 仍记录点击")

    update = apply_click_update(
        user,
        doc_id=req.doc_id,
        source=source,
        tag=tag,
        query=req.query,
        dwell_ms=req.dwell_ms,
    )
    res = users.update_one({"user_id": user["user_id"]}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user vanished"
        )
    fresh = users.find_one({"user_id": user["user_id"]})
    assert fresh is not None
    return _to_profile(fresh)
