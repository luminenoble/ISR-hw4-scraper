"""用户注册 / 登录 / profile 路由（design.md §3.5 / sec5 §7 M6-1）。

- 注册：argon2id 哈希密码，写 Mongo `users`
- 登录：校验 + 颁发 JWT
- /me GET：返回当前 profile（剔除密码与向量）
- /me PATCH：改 interests / preferred_sources / default_alpha / default_beta

匿名搜索仍允许；此处的强制登录只对 /me 生效。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.errors import DuplicateKeyError

from api.deps import get_current_user_required, get_users_col
from api.schemas import (
    LoginRequest,
    ProfilePatch,
    RegisterRequest,
    TokenResponse,
    UserProfile,
)
from api.security import (
    create_access_token,
    hash_password,
    make_user_id,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _to_profile(user: dict) -> UserProfile:
    return UserProfile(
        user_id=user["user_id"],
        email=user["email"],
        created_at=user.get("created_at", ""),
        interests=list(user.get("interests", [])),
        preferred_sources=dict(user.get("preferred_sources", {})),
        preferred_tag_weights=dict(user.get("preferred_tag_weights", {})),
        default_alpha=float(user.get("default_alpha", 0.3)),
        default_beta=float(user.get("default_beta", 0.5)),
        click_count=len(user.get("click_doc_ids", [])),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    req: RegisterRequest,
    users=Depends(get_users_col),
) -> TokenResponse:
    user_id = make_user_id()
    now = datetime.now(UTC).isoformat(timespec="seconds")
    doc = {
        "user_id": user_id,
        "email": req.email.strip().lower(),
        "password_hash": hash_password(req.password),
        "created_at": now,
        "interests": req.interests,
        "preferred_sources": req.preferred_sources,
        "preferred_tag_weights": req.preferred_tag_weights,
        "click_history": [],
        "click_doc_ids": [],
        "interest_vec": None,
        "interest_vec_n": 0,
        "default_alpha": req.default_alpha,
        "default_beta": req.default_beta,
    }
    try:
        users.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email already registered"
        ) from None
    return TokenResponse(access_token=create_access_token(user_id), user_id=user_id)


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, users=Depends(get_users_col)) -> TokenResponse:
    user = users.find_one({"email": req.email.strip().lower()})
    if not user or not verify_password(req.password, user["password_hash"]):
        # 故意不区分 user-not-found / wrong-password，避免邮箱枚举
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
        )
    return TokenResponse(
        access_token=create_access_token(user["user_id"]), user_id=user["user_id"]
    )


@router.get("/me", response_model=UserProfile)
def me(user: Annotated[dict, Depends(get_current_user_required)]) -> UserProfile:
    return _to_profile(user)


@router.patch("/me", response_model=UserProfile)
def patch_me(
    patch: ProfilePatch,
    user: Annotated[dict, Depends(get_current_user_required)],
    users=Depends(get_users_col),
) -> UserProfile:
    update: dict = {}
    if patch.interests is not None:
        update["interests"] = patch.interests
    if patch.preferred_sources is not None:
        update["preferred_sources"] = patch.preferred_sources
    if patch.preferred_tag_weights is not None:
        update["preferred_tag_weights"] = patch.preferred_tag_weights
    if patch.default_alpha is not None:
        update["default_alpha"] = patch.default_alpha
    if patch.default_beta is not None:
        update["default_beta"] = patch.default_beta
    if update:
        users.update_one({"user_id": user["user_id"]}, {"$set": update})
    fresh = users.find_one({"user_id": user["user_id"]})
    assert fresh is not None
    return _to_profile(fresh)
