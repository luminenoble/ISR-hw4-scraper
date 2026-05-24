"""auth/security 单测：argon2 哈希 + JWT 编解码 + bearer 解析。

不依赖 Mongo / FastAPI lifespan，纯函数测试。
"""

from __future__ import annotations

import time

import pytest

from api.security import (
    create_access_token,
    decode_token,
    hash_password,
    make_user_id,
    verify_password,
)


def test_hash_password_roundtrip():
    pw = "correct horse battery staple"
    h = hash_password(pw)
    assert h != pw
    assert h.startswith("$argon2")
    assert verify_password(pw, h) is True
    assert verify_password("wrong", h) is False


def test_hash_password_unique_salt():
    """同一明文哈希两次应得到不同串（salt 随机）。"""
    pw = "hunter2"
    assert hash_password(pw) != hash_password(pw)


def test_verify_password_handles_garbage_hash():
    assert verify_password("anything", "not-a-valid-hash") is False


def test_make_user_id_format_and_uniqueness():
    a = make_user_id()
    b = make_user_id()
    assert a.startswith("u_")
    assert len(a) >= 10
    assert a != b


def test_jwt_roundtrip_with_subject():
    uid = "u_test123"
    tok = create_access_token(uid)
    payload = decode_token(tok)
    assert payload is not None
    assert payload["sub"] == uid
    assert "exp" in payload and "iat" in payload
    assert payload["exp"] > payload["iat"]


def test_jwt_carries_extra_claims():
    tok = create_access_token("u_x", extra={"scope": "admin"})
    payload = decode_token(tok)
    assert payload is not None
    assert payload.get("scope") == "admin"


def test_decode_token_rejects_garbage():
    assert decode_token("not.a.jwt") is None
    assert decode_token("") is None


def test_decode_token_rejects_expired(monkeypatch):
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "0")
    tok = create_access_token("u_exp")
    # exp 与 iat 同秒，等 1s 后必然过期
    time.sleep(1.1)
    assert decode_token(tok) is None


def test_decode_token_rejects_wrong_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "secret-a")
    tok = create_access_token("u_swap")
    monkeypatch.setenv("JWT_SECRET", "secret-b")
    assert decode_token(tok) is None


def test_parse_bearer_helper():
    from api.deps import _parse_bearer

    assert _parse_bearer(None) is None
    assert _parse_bearer("") is None
    assert _parse_bearer("Token abc") is None
    assert _parse_bearer("bearer xyz") == "xyz"
    assert _parse_bearer("Bearer   xyz  ") == "xyz"


@pytest.mark.parametrize(
    "header",
    ["Bearer", "Bearer ", "  ", "Basic dXNlcjpwYXNz"],
)
def test_parse_bearer_rejects_malformed(header: str):
    from api.deps import _parse_bearer

    out = _parse_bearer(header)
    # 任何非 "Bearer <token>" 形式都应返回 None 或空串
    assert not out
