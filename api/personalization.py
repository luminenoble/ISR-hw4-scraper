"""个性化逻辑：用户档案 → ranking PersonalBoost 参数 / 隐式反馈增量更新。

设计取舍：
- 不在线学习用户兴趣向量×doc embedding（M6 推迟），仅用 source/tag/click 三项
- click_doc_ids 上限 500，FIFO 淘汰；click_history 上限 200，保留 dwell_ms
- 偏好权重指数累计 1.02，超过 1 时整体归一防爆炸；缺省 source/tag 起始权重 0.1
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

CLICK_DOC_IDS_LIMIT = 500
CLICK_HISTORY_LIMIT = 200
PREF_BUMP_FACTOR = 1.02
PREF_INIT = 0.1


def boost_params_for(user: dict | None) -> dict[str, Any]:
    """从 user 文档抽出传给 build_function_score 的 PersonalBoost kwargs。

    匿名用户（user=None）→ beta=0，等同关闭个性化。
    用户禁用（default_beta=0）→ 同上。
    """
    if not user:
        return {"beta": 0.0}
    beta = float(user.get("default_beta", 0.0) or 0.0)
    if beta <= 0:
        return {"beta": 0.0}
    return {
        "beta": beta,
        "pref_sources": dict(user.get("preferred_sources") or {}),
        "pref_tags": dict(user.get("preferred_tag_weights") or {}),
        "click_set": list(user.get("click_doc_ids") or []),
    }


def _bump(weights: dict[str, float], key: str) -> dict[str, float]:
    cur = float(weights.get(key, PREF_INIT))
    cur *= PREF_BUMP_FACTOR
    weights[key] = cur
    # 任意权重过 1 时按最大值归一，避免长期点击单一类目把权重推到失控
    m = max(weights.values())
    if m > 1.0:
        weights = {k: v / m for k, v in weights.items()}
    return weights


def apply_click_update(
    user: dict,
    *,
    doc_id: str,
    source: str | None,
    tag: str | None,
    query: str | None,
    dwell_ms: int | None,
) -> dict[str, Any]:
    """根据一次点击事件，构造给 users.update_one 用的 $set/$push 增量。

    不直接落库，返回 update 字典让 router 注入；便于单测。
    """
    now = datetime.now(UTC).isoformat(timespec="seconds")

    pref_sources = dict(user.get("preferred_sources") or {})
    pref_tags = dict(user.get("preferred_tag_weights") or {})
    if source:
        pref_sources = _bump(pref_sources, source)
    if tag:
        pref_tags = _bump(pref_tags, tag)

    click_ids = list(user.get("click_doc_ids") or [])
    if doc_id in click_ids:
        click_ids.remove(doc_id)  # 移到最新位置
    click_ids.append(doc_id)
    if len(click_ids) > CLICK_DOC_IDS_LIMIT:
        click_ids = click_ids[-CLICK_DOC_IDS_LIMIT:]

    click_history = list(user.get("click_history") or [])
    click_history.append(
        {"doc_id": doc_id, "ts": now, "dwell_ms": dwell_ms, "query": query}
    )
    if len(click_history) > CLICK_HISTORY_LIMIT:
        click_history = click_history[-CLICK_HISTORY_LIMIT:]

    return {
        "preferred_sources": pref_sources,
        "preferred_tag_weights": pref_tags,
        "click_doc_ids": click_ids,
        "click_history": click_history,
    }
