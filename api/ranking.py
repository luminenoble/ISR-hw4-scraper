"""排序公式接线（design.md §3.4）。

公式（β·PersonalBoost 留 M6）：

    score = (1-α) × [ w1·bm25_norm + w2·pagerank ]
          +  α    × [ w3·semantic × obscurity ]
          +  β    × personal_boost

实现：用 ES ``function_score`` + ``script_score``，一次查询完成。

- α=0：纯 BM25 + PageRank 加权（M4 行为 + 链接分析）
- α=1：纯语义召回 × Obscurity（依赖 embedding 字段已写入）
- 0<α<1：连续插值

如 embedding 字段不存在（M5 编码阶段还没跑完），α 路径会降级为
``BM25 × Obscurity``（仍能利用 obscurity 拉低过热点）。
"""

from __future__ import annotations

from typing import Any

# 默认权重（design.md §3.4 提议值）；可由查询参数覆盖
DEFAULT_W1 = 1.0  # BM25 normalized
DEFAULT_W2 = 1.0  # PageRank
DEFAULT_W3 = 1.0  # Semantic similarity
DEFAULT_BETA = 0.5  # PersonalBoost 总权重（仅登录用户启用）
# bm25 归一化常量：score / (score + BM25_K)，K 经验值
BM25_K = 10.0
# PersonalBoost 内部三项权重：source / tag / 历史点击
PB_W_SOURCE = 0.4
PB_W_TAG = 0.4
PB_W_CLICK = 0.2


def build_function_score(
    inner_query: dict[str, Any],
    *,
    alpha: float,
    w1: float,
    w2: float,
    w3: float,
    query_vector: list[float] | None,
    use_embedding: bool,
    beta: float = 0.0,
    pref_sources: dict[str, float] | None = None,
    pref_tags: dict[str, float] | None = None,
    click_set: list[str] | None = None,
) -> dict[str, Any]:
    """把 inner_query（多字段 BM25 query）包成带公式打分的 function_score。

    Args:
        inner_query: 关键词 / 短语 / 通配匹配子句（kind 决定 must 内容）
        alpha: 发散度 [0, 1]
        w1/w2/w3: 三项权重
        query_vector: 用户查询的 embedding（α>0 且有向量时启用 knn-style 相似度）
        use_embedding: 是否真的使用语义项；False 时退化为 BM25×Obscurity
        beta: PersonalBoost 总权重，0 表示不开启（匿名 / 用户禁用个性化时）
        pref_sources: {source: weight}，doc.source 命中时贡献 PB_W_SOURCE × weight
        pref_tags:    {tag: weight}，   doc.tag 命中时贡献 PB_W_TAG × weight
        click_set:    历史点击的 doc_id 列表，命中文档贡献 PB_W_CLICK × 1
    """
    # 把 _score（BM25 原始分）压到 [0,1]：bm25 / (bm25 + K)
    bm25_norm_src = f"_score / (_score + {BM25_K})"

    # 公式拆三项，缺项填 0。Painless 里 doc['x'].value 缺失时报错，
    # 故所有字段读取都先用 doc.containsKey 加 size() 守护。
    pagerank_src = (
        "double pr = (doc.containsKey('pagerank') && doc['pagerank'].size() > 0) "
        "? doc['pagerank'].value : 0.0;"
    )
    obscurity_src = (
        "double obs = (doc.containsKey('obscurity') && doc['obscurity'].size() > 0) "
        "? doc['obscurity'].value : 1.0;"
    )

    if use_embedding and query_vector is not None and alpha > 0:
        # cosineSimilarity 返回 [-1,1]，加 1.0 再除 2 映到 [0,1] 防止负贡献
        sem_src = (
            "double sem = (doc.containsKey('embedding') && doc['embedding'].size() > 0) "
            "? (cosineSimilarity(params.qv, 'embedding') + 1.0) / 2.0 : 0.0;"
        )
        params: dict[str, Any] = {
            "alpha": alpha,
            "w1": w1,
            "w2": w2,
            "w3": w3,
            "qv": query_vector,
            "bm25k": BM25_K,
        }
    else:
        # 没向量：alpha 路径退化为 obs，让稀有度仍能起作用
        sem_src = "double sem = 1.0;"  # 占位为 1，与 obs 相乘后等同 obs
        params = {"alpha": alpha, "w1": w1, "w2": w2, "w3": w3, "bm25k": BM25_K}

    # PersonalBoost：β=0 时 script 里只算 0；β>0 时按 source/tag/click 三项加权
    has_pb = beta > 0 and (pref_sources or pref_tags or click_set)
    if has_pb:
        params["beta"] = beta
        params["pb_w_src"] = PB_W_SOURCE
        params["pb_w_tag"] = PB_W_TAG
        params["pb_w_clk"] = PB_W_CLICK
        params["pref_sources"] = pref_sources or {}
        params["pref_tags"] = pref_tags or {}
        # ES Painless 把 List 暴露为可调用 .contains() 的对象
        params["click_set"] = click_set or []
        personal_src = """
            double ps = 0.0;
            if (doc.containsKey('source') && doc['source'].size() > 0) {
                String s = doc['source'].value;
                if (((Map)params.pref_sources).containsKey(s)) {
                    ps += params.pb_w_src * ((Number)((Map)params.pref_sources).get(s)).doubleValue();
                }
            }
            if (doc.containsKey('tag') && doc['tag'].size() > 0) {
                String t = doc['tag'].value;
                if (((Map)params.pref_tags).containsKey(t)) {
                    ps += params.pb_w_tag * ((Number)((Map)params.pref_tags).get(t)).doubleValue();
                }
            }
            if (doc.containsKey('doc_id') && doc['doc_id'].size() > 0) {
                String did = doc['doc_id'].value;
                if (((List)params.click_set).contains(did)) {
                    ps += params.pb_w_clk;
                }
            }
            double pb_term = params.beta * ps;
        """
    else:
        personal_src = "double pb_term = 0.0;"

    script_source = f"""
        double bm25 = {bm25_norm_src};
        {pagerank_src}
        {obscurity_src}
        {sem_src}
        {personal_src}
        double bm_term = params.w1 * bm25 + params.w2 * pr;
        double sem_term = params.w3 * sem * obs;
        return (1.0 - params.alpha) * bm_term + params.alpha * sem_term + pb_term;
    """

    return {
        "function_score": {
            "query": inner_query,
            "script_score": {
                "script": {"source": script_source, "params": params}
            },
            "boost_mode": "replace",
        }
    }
