"""密码哈希与 JWT 编解码。

- 密码：argon2id（`argon2-cffi`），抗 GPU 暴破强于 bcrypt
- 会话：JWT HS256，默认过期 7 天；课程作业不上 refresh token
- SECRET_KEY / 过期时间走 env，缺省值仅用于本地开发
"""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

JWT_ALG = "HS256"

# 仅 dev 默认值；生产 / 评测必须由 .env 覆盖
_DEFAULT_SECRET = "isr-dev-secret-change-me-please-32+bytes"


def _secret_key() -> str:
    return os.getenv("JWT_SECRET", _DEFAULT_SECRET)


def _expire_minutes() -> int:
    return int(os.getenv("JWT_EXPIRE_MINUTES", str(60 * 24 * 7)))


_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False
    return True


def make_user_id() -> str:
    return "u_" + secrets.token_urlsafe(9)


def create_access_token(user_id: str, *, extra: dict | None = None) -> str:
    now = datetime.now(UTC)
    payload: dict = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=_expire_minutes())).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, _secret_key(), algorithm=JWT_ALG)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, _secret_key(), algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        return None
