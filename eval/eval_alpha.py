"""α 发散度评测：对样本 query 跑 α=0/0.3/0.7/1.0 四档。

直接调 FastAPI `/search` 端点（要求 uvicorn 在跑），不走内部函数；
这样能把 query embedding、function_score、日志写入这整条链路都跑通，
评测结果反映**真实在线行为**。

输出：
- 每档 top-10 的 source 分布、平均 obscurity、平均 pagerank
- 相邻 α 档之间 top-10 的 Jaccard / RBO 重叠度
- 整体汇总表写到 ``reports/eval_alpha.md``
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from statistics import mean
from typing import Any

import httpx

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from eval.common import INDEX_NAME, SAMPLE_QUERIES, get_es, jaccard, rbo  # noqa: E402

API_HOST = os.getenv("ISR_API_HOST", "http://127.0.0.1:8000")
ALPHA_GRID: list[float] = [0.0, 0.3, 0.7, 1.0]
TOP_K = 10


def hit_via_api(client: httpx.Client, q: str, alpha: float) -> list[dict[str, Any]]:
    """走 /search 拿真实排序结果。"""
    r = client.get(
        f"{API_HOST}/search",
        params={"q": q, "size": TOP_K, "alpha": alpha, "beta": 0.0},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["hits"]


def enrich(es, doc_ids: list[str]) -> dict[str, dict[str, Any]]:
    """批量补 source/obscurity/pagerank。"""
    if not doc_ids:
        return {}
    resp = es.mget(
        index=INDEX_NAME,
        body={"ids": doc_ids},
        _source_includes=["source", "obscurity", "pagerank", "popularity", "tag"],
    )
    return {d["_id"]: d.get("_source") or {} for d in resp["docs"] if d.get("found")}


def main() -> None:
    es = get_es()
    out_path = _PROJECT_ROOT / "reports" / "eval_alpha.md"
    out_path.parent.mkdir(exist_ok=True)

    per_query: list[dict[str, Any]] = []
    overall_jaccard: dict[tuple[float, float], list[float]] = {}
    overall_rbo: dict[tuple[float, float], list[float]] = {}
    overall_obs: dict[float, list[float]] = {a: [] for a in ALPHA_GRID}
    overall_pr: dict[float, list[float]] = {a: [] for a in ALPHA_GRID}
    overall_src: dict[float, dict[str, int]] = {a: {} for a in ALPHA_GRID}

    with httpx.Client(trust_env=False, timeout=60.0) as client:
        for q in SAMPLE_QUERIES:
            hits_by_alpha: dict[float, list[dict[str, Any]]] = {}
            ids_by_alpha: dict[float, list[str]] = {}
            for a in ALPHA_GRID:
                hits = hit_via_api(client, q, a)
                hits_by_alpha[a] = hits
                ids_by_alpha[a] = [h["doc_id"] for h in hits]

            # 批量补元数据（去重一次）
            all_ids = sorted({d for ids in ids_by_alpha.values() for d in ids})
            meta = enrich(es, all_ids)

            alpha_summary: dict[float, dict[str, Any]] = {}
            for a in ALPHA_GRID:
                obs_vals = [meta.get(d, {}).get("obscurity", 0.0) for d in ids_by_alpha[a]]
                pr_vals = [meta.get(d, {}).get("pagerank", 0.0) for d in ids_by_alpha[a]]
                src_dist: dict[str, int] = {}
                for d in ids_by_alpha[a]:
                    s = meta.get(d, {}).get("source", "?")
                    src_dist[s] = src_dist.get(s, 0) + 1
                alpha_summary[a] = {
                    "avg_obscurity": mean(obs_vals) if obs_vals else 0.0,
                    "avg_pagerank": mean(pr_vals) if pr_vals else 0.0,
                    "source_dist": src_dist,
                    "top1_title": hits_by_alpha[a][0]["title"] if hits_by_alpha[a] else None,
                }
                overall_obs[a].extend(obs_vals)
                overall_pr[a].extend(pr_vals)
                for s, n in src_dist.items():
                    overall_src[a][s] = overall_src[a].get(s, 0) + n

            # 相邻档对比 + 极端对比
            pairs = [(0.0, 0.3), (0.3, 0.7), (0.7, 1.0), (0.0, 1.0)]
            overlaps: dict[str, dict[str, float]] = {}
            for a1, a2 in pairs:
                j = jaccard(ids_by_alpha[a1], ids_by_alpha[a2])
                rb = rbo(ids_by_alpha[a1], ids_by_alpha[a2])
                key = f"α{a1}↔α{a2}"
                overlaps[key] = {"jaccard": j, "rbo": rb}
                overall_jaccard.setdefault((a1, a2), []).append(j)
                overall_rbo.setdefault((a1, a2), []).append(rb)

            per_query.append({"q": q, "by_alpha": alpha_summary, "overlap": overlaps})
            print(
                f"[{q!r}] α=0 top1={alpha_summary[0.0]['top1_title']!r:50s} "
                f"α=1 top1={alpha_summary[1.0]['top1_title']!r}"
            )

    # 写 Markdown 报告
    lines: list[str] = [
        "# α 发散度评测报告",
        "",
        f"- 评测 query 数：{len(SAMPLE_QUERIES)}",
        f"- α 档位：{ALPHA_GRID}",
        f"- 每档 top-K：{TOP_K}",
        f"- API：`{API_HOST}/search?beta=0`（关闭个性化以孤立 α 影响）",
        "",
        "## 1. 全局聚合",
        "",
        "| α | avg obscurity | avg pagerank | 主导 source | 第二 source |",
        "|---|---|---|---|---|",
    ]
    for a in ALPHA_GRID:
        obs_avg = mean(overall_obs[a]) if overall_obs[a] else 0.0
        pr_avg = mean(overall_pr[a]) if overall_pr[a] else 0.0
        sorted_src = sorted(overall_src[a].items(), key=lambda kv: -kv[1])
        s1 = f"{sorted_src[0][0]}({sorted_src[0][1]})" if sorted_src else "-"
        s2 = f"{sorted_src[1][0]}({sorted_src[1][1]})" if len(sorted_src) > 1 else "-"
        lines.append(f"| {a} | {obs_avg:.4f} | {pr_avg:.2e} | {s1} | {s2} |")

    lines += ["", "## 2. 档间重叠度（平均）", "", "| 对比 | Jaccard | RBO |", "|---|---|---|"]
    for (a1, a2), js in overall_jaccard.items():
        rbs = overall_rbo[(a1, a2)]
        lines.append(f"| α{a1}↔α{a2} | {mean(js):.3f} | {mean(rbs):.3f} |")

    lines += ["", "## 3. 逐 query 明细", ""]
    for item in per_query:
        lines.append(f"### `{item['q']}`")
        lines.append("")
        lines.append("| α | top1 | avg obs | avg pr | source 分布 |")
        lines.append("|---|---|---|---|---|")
        for a in ALPHA_GRID:
            s = item["by_alpha"][a]
            dist = ", ".join(f"{k}:{v}" for k, v in s["source_dist"].items())
            lines.append(
                f"| {a} | {s['top1_title']!r} | {s['avg_obscurity']:.3f} | "
                f"{s['avg_pagerank']:.2e} | {dist} |"
            )
        lines.append("")
        lines.append("重叠度：")
        for k, v in item["overlap"].items():
            lines.append(f"- {k}: Jaccard={v['jaccard']:.3f}, RBO={v['rbo']:.3f}")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    json_path = out_path.with_suffix(".json")
    json_path.write_text(
        json.dumps(
            {
                "alpha_grid": ALPHA_GRID,
                "per_query": per_query,
                "overall_obs": {
                    str(a): mean(vs) if vs else 0.0 for a, vs in overall_obs.items()
                },
                "overall_jaccard": {f"{a1}-{a2}": mean(vs) for (a1, a2), vs in overall_jaccard.items()},
                "overall_rbo": {f"{a1}-{a2}": mean(vs) for (a1, a2), vs in overall_rbo.items()},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n✔ 报告 -> {out_path}")
    print(f"✔ JSON -> {json_path}")


if __name__ == "__main__":
    main()
