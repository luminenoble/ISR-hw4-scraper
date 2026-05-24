"""个性化排序评测：构造一个偏 reddit/fanon 的虚拟用户，对比 β=0 与 β>0。

流程：
  1. 注册 user_R（preferred_sources={"reddit":1.0}, preferred_tag_weights={"fanon":1.0}）
  2. 同一组 query 跑 β=0 vs β=1.5 vs β=3.0
  3. 统计 top-10 中 reddit 占比、fanon 占比、点击-命中文档前后差异
  4. 报告 reports/eval_personalization.md

不污染线上用户：用 secrets 生成临时 email。
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path
from statistics import mean
from typing import Any

import httpx

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from eval.common import SAMPLE_QUERIES  # noqa: E402

API_HOST = os.getenv("ISR_API_HOST", "http://127.0.0.1:8000")
BETA_GRID = [0.0, 1.5, 3.0]
TOP_K = 10


def register(c: httpx.Client, **kwargs) -> str:
    email = f"eval_pers_{secrets.token_hex(4)}@example.com"
    password = secrets.token_urlsafe(12)
    body = {
        "email": email,
        "password": password,
        **kwargs,
    }
    r = c.post("/auth/register", json=body)
    r.raise_for_status()
    return r.json()["access_token"]


def search(c: httpx.Client, q: str, beta: float, token: str) -> list[dict[str, Any]]:
    r = c.get(
        "/search",
        params={"q": q, "size": TOP_K, "alpha": 0.0, "beta": beta},
        headers={"authorization": f"Bearer {token}"},
    )
    r.raise_for_status()
    return r.json()["hits"]


def main() -> None:
    with httpx.Client(trust_env=False, timeout=60.0, base_url=API_HOST) as c:
        # 注意：boost_params_for 要求 user.default_beta > 0 才会回填 pref_sources/tags
        # 把 default_beta 设为正值，URL 的 β grid 才能真正生效
        token = register(
            c,
            preferred_sources={"reddit": 1.0, "fandom": 0.0, "wiki": 0.0},
            preferred_tag_weights={"fanon": 1.0, "canon": 0.0},
            default_alpha=0.0,
            default_beta=1.0,
        )

        per_query: list[dict[str, Any]] = []
        beta_reddit_pct: dict[float, list[float]] = {b: [] for b in BETA_GRID}
        beta_top1_ids: dict[float, list[str]] = {b: [] for b in BETA_GRID}

        for q in SAMPLE_QUERIES:
            row: dict[str, Any] = {"q": q, "by_beta": {}}
            id_lists: dict[float, list[str]] = {}
            for b in BETA_GRID:
                hits = search(c, q, b, token)
                ids = [h["doc_id"] for h in hits]
                id_lists[b] = ids
                reddit_n = sum(1 for h in hits if h.get("source") == "reddit")
                fandom_n = sum(1 for h in hits if h.get("source") == "fandom")
                wiki_n = sum(1 for h in hits if h.get("source") == "wiki")
                row["by_beta"][b] = {
                    "reddit_pct": reddit_n / max(1, len(hits)),
                    "fandom": fandom_n,
                    "wiki": wiki_n,
                    "reddit": reddit_n,
                    "top1": hits[0]["title"] if hits else None,
                    "top1_source": hits[0].get("source") if hits else None,
                }
                beta_reddit_pct[b].append(reddit_n / max(1, len(hits)))
                beta_top1_ids[b].append(ids[0] if ids else "")

            # β=0 与 β=3.0 之间 top-10 重叠
            sa, sb = set(id_lists[0.0]), set(id_lists[3.0])
            row["jaccard_0_vs_3"] = len(sa & sb) / max(1, len(sa | sb))
            row["top1_shifted"] = id_lists[0.0][:1] != id_lists[3.0][:1]
            per_query.append(row)
            print(
                f"[{q!r}] β=0 reddit%={row['by_beta'][0.0]['reddit_pct']:.2f} "
                f"β=3 reddit%={row['by_beta'][3.0]['reddit_pct']:.2f} "
                f"top1 shifted={row['top1_shifted']}"
            )

    # 写报告
    out = _PROJECT_ROOT / "reports" / "eval_personalization.md"
    out.parent.mkdir(exist_ok=True)
    lines = [
        "# 个性化排序评测（β · PersonalBoost）",
        "",
        "## 配置",
        "",
        "- 虚拟用户偏好：`preferred_sources={reddit:1.0, fandom:0.0, wiki:0.0}`,"
        " `preferred_tag_weights={fanon:1.0, canon:0.0}`",
        f"- β 档位：{BETA_GRID}",
        f"- 每档 top-K：{TOP_K}, α 固定为 0（孤立 β 影响）",
        f"- 评测 query 数：{len(SAMPLE_QUERIES)}",
        "",
        "## 全局聚合",
        "",
        "| β | 平均 reddit 占比 (top-10) | β=0 与该档 top1 变化次数 |",
        "|---|---|---|",
    ]
    base_top1 = beta_top1_ids[0.0]
    for b in BETA_GRID:
        avg_red = mean(beta_reddit_pct[b]) if beta_reddit_pct[b] else 0.0
        shifted = sum(1 for i, t in enumerate(beta_top1_ids[b]) if t != base_top1[i])
        lines.append(f"| {b} | {avg_red:.2%} | {shifted}/{len(SAMPLE_QUERIES)} |")

    lines += ["", "## 逐 query 明细", ""]
    for r in per_query:
        lines.append(f"### `{r['q']}`")
        lines.append("")
        lines.append("| β | top1 | top1 source | reddit/top10 | wiki | fandom |")
        lines.append("|---|---|---|---|---|---|")
        for b in BETA_GRID:
            d = r["by_beta"][b]
            lines.append(
                f"| {b} | {d['top1']!r} | {d['top1_source']} | "
                f"{d['reddit']}/{TOP_K} | {d['wiki']} | {d['fandom']} |"
            )
        lines.append(
            f"\n- β=0 vs β=3.0 top-10 Jaccard = **{r['jaccard_0_vs_3']:.3f}**"
            f"，top1 变化 = **{r['top1_shifted']}**"
        )
        lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✔ {out}")


if __name__ == "__main__":
    main()
