"""6 种查询的端到端 case study（对应作业 2.3.1–2.3.6）。

每种查询跑一个代表 query，记录：耗时 / 命中数 / kind 分流 / top-3 / 行为。
报告输出到 ``reports/eval_queries.md``。
"""

from __future__ import annotations

import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any

import httpx

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

API_HOST = os.getenv("ISR_API_HOST", "http://127.0.0.1:8000")


def _client() -> httpx.Client:
    return httpx.Client(trust_env=False, timeout=60.0, base_url=API_HOST)


def case_match(c: httpx.Client) -> dict[str, Any]:
    """2.3.1 站内查询：multi_match across title/anchors/body."""
    t0 = time.perf_counter()
    r = c.get("/search", params={"q": "Luffy strawhat", "size": 5, "alpha": 0.0})
    r.raise_for_status()
    j = r.json()
    return {
        "name": "站内查询 (match)",
        "query": "Luffy strawhat",
        "kind": j["kind"],
        "total": j["total"],
        "took_ms_server": j["took_ms"],
        "took_ms_e2e": (time.perf_counter() - t0) * 1000,
        "top": [{"t": h["title"], "s": h["source"]} for h in j["hits"][:3]],
    }


def case_document(c: httpx.Client) -> dict[str, Any]:
    """2.3.2 文档查询：source=document filter."""
    t0 = time.perf_counter()
    r = c.get(
        "/search",
        params={"q": "character", "size": 5, "alpha": 0.0, "source": "document"},
    )
    r.raise_for_status()
    j = r.json()
    return {
        "name": "文档查询 (document filter)",
        "query": "character + source:document",
        "kind": j["kind"],
        "total": j["total"],
        "took_ms_server": j["took_ms"],
        "took_ms_e2e": (time.perf_counter() - t0) * 1000,
        "filters_applied": j["filters"],
        "top": [{"t": h["title"], "s": h["source"]} for h in j["hits"][:3]],
    }


def case_phrase(c: httpx.Client) -> dict[str, Any]:
    """2.3.3 短语查询：引号触发 match_phrase。"""
    t0 = time.perf_counter()
    r = c.get("/search", params={"q": '"alternate universe"', "size": 5, "alpha": 0.0})
    r.raise_for_status()
    j = r.json()
    # 对比：去引号的同样查询，hit 数应不同
    r2 = c.get("/search", params={"q": "alternate universe", "size": 5, "alpha": 0.0})
    j2 = r2.json()
    return {
        "name": "短语查询 (phrase)",
        "query": '"alternate universe"',
        "kind": j["kind"],
        "total_phrase": j["total"],
        "total_loose": j2["total"],
        "phrase_loose_ratio": j["total"] / max(1, j2["total"]),
        "took_ms_server": j["took_ms"],
        "took_ms_e2e": (time.perf_counter() - t0) * 1000,
        "top": [{"t": h["title"], "s": h["source"]} for h in j["hits"][:3]],
    }


def case_wildcard(c: httpx.Client) -> dict[str, Any]:
    """2.3.4 通配查询：query_string 带 *? 通配符。"""
    t0 = time.perf_counter()
    r = c.get("/search", params={"q": "naru*", "size": 5, "alpha": 0.0})
    r.raise_for_status()
    j = r.json()
    return {
        "name": "通配查询 (wildcard)",
        "query": "naru*",
        "kind": j["kind"],
        "total": j["total"],
        "took_ms_server": j["took_ms"],
        "took_ms_e2e": (time.perf_counter() - t0) * 1000,
        "top": [{"t": h["title"], "s": h["source"]} for h in j["hits"][:3]],
    }


def case_log(c: httpx.Client) -> dict[str, Any]:
    """2.3.5 查询日志：注册临时用户 → 跑两条 query → 拉 /logs/me 验证记录。"""
    # 注册一个一次性账户
    email = f"eval_{secrets.token_hex(4)}@example.com"
    password = secrets.token_urlsafe(12)
    reg = c.post("/auth/register", json={"email": email, "password": password})
    reg.raise_for_status()
    token = reg.json()["access_token"]
    headers = {"authorization": f"Bearer {token}"}

    t0 = time.perf_counter()
    c.get("/search", params={"q": "Luffy", "size": 3}, headers=headers).raise_for_status()
    c.get(
        "/search", params={"q": '"alternate universe"', "size": 3}, headers=headers
    ).raise_for_status()

    logs = c.get("/logs/me", params={"limit": 10}, headers=headers).json()
    return {
        "name": "查询日志 (query log)",
        "query": "(注册→2 次搜索→读取日志)",
        "logged_count": logs["count"],
        "took_ms_e2e": (time.perf_counter() - t0) * 1000,
        "sample": [
            {"q": it["query"], "kind": it["kind"], "total": it["total"]}
            for it in logs["items"][:3]
        ],
    }


def case_snapshot(c: httpx.Client) -> dict[str, Any]:
    """2.3.6 网页快照：搜一条 → /snapshot/{doc_id} → 校验返回 HTML。"""
    sr = c.get("/search", params={"q": "Luffy", "size": 1, "alpha": 0.0}).json()
    if not sr["hits"]:
        return {"name": "网页快照 (snapshot)", "error": "no hit to snapshot"}
    doc_id = sr["hits"][0]["doc_id"]

    t0 = time.perf_counter()
    r = c.get(f"/snapshot/{doc_id}")
    e2e = (time.perf_counter() - t0) * 1000
    ok = r.status_code == 200
    return {
        "name": "网页快照 (snapshot)",
        "doc_id": doc_id,
        "status": r.status_code,
        "content_type": r.headers.get("content-type", ""),
        "bytes": len(r.content),
        "x_snapshot_url": r.headers.get("x-snapshot-url", ""),
        "took_ms_e2e": e2e,
        "ok": ok,
    }


def main() -> None:
    results: list[dict[str, Any]] = []
    with _client() as c:
        for fn in (
            case_match,
            case_document,
            case_phrase,
            case_wildcard,
            case_log,
            case_snapshot,
        ):
            print(f"=> {fn.__name__} ...")
            results.append(fn(c))

    out_path = _PROJECT_ROOT / "reports" / "eval_queries.md"
    out_path.parent.mkdir(exist_ok=True)
    lines: list[str] = [
        "# 6 种查询 case study",
        "",
        f"- API: `{API_HOST}`",
        "- 每条 case 走真实 FastAPI 路由 + ES 后端，记录服务端 took 与端到端耗时",
        "",
    ]
    for r in results:
        lines.append(f"## {r['name']}")
        lines.append("")
        for k, v in r.items():
            if k == "name":
                continue
            if isinstance(v, (list, dict)):
                lines.append(f"- **{k}**:")
                if isinstance(v, list):
                    for item in v:
                        lines.append(f"  - {item}")
                else:
                    for kk, vv in v.items():
                        lines.append(f"  - {kk} = {vv}")
            else:
                lines.append(f"- **{k}**: `{v}`")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✔ {out_path}")


if __name__ == "__main__":
    main()
