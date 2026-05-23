# Sec.5 PageRank + bge-m3 + 排序公式接线（M5 阶段）

> 对应里程碑：`design.md §7 — M5 PageRank + embedding + 排序公式整合`
> 完成日期：2026-05-23
> 上游依赖：`docs/sec4-summary.md`（ES 96064 docs 已索引、6 路查询跑通）

## 1. 交付物清单

| 路径 | 性质 | 作用 |
|---|---|---|
| `indexer/pagerank.py` | 新增 | 构图（urljoin 内链）+ networkx PageRank + popularity（in-degree）+ obscurity，bulk `_update` 写回 ES |
| `indexer/embed.py` | 新增 | bge-m3 批量编码 + bulk `_update` embedding 字段；Mongo 端 `embedded_at` 标记支持 `--resume` |
| `api/ranking.py` | 新增 | `function_score` + `script_score` 拼装公式 |
| `api/deps.py` | 修改 | 加 `get_embedder()` 惰性加载 bge-m3（用 env `BGE_M3_MODEL_PATH`） |
| `api/routers/search.py` | 修改 | `/search` 加 `alpha/w1/w2/w3` 参数，集成 ranking |
| `tests/test_ranking.py` | 新增 | 7 个 case，覆盖公式分量与降级路径 |
| `data/graph/pagerank.csv` | 数据 | 离线 PR 落盘备查（doc_id, pagerank, popularity, obscurity） |
| `~/model/bge-m3/` | 数据 | 2.3GB 模型权重，env `BGE_M3_MODEL_PATH` 指向 |
| `docs/sec5-summary.md` | 新增 | 本文 |

## 2. 关键决策

### 2.1 Popularity 走 inbound degree 而非真实数据

按规划 §4 Q1 决策。reddit / wiki / fandom 真实拉数据估时 5-6 小时（fandom 是瓶颈，无公开 API），inbound degree 5 分钟完成且与 PageRank 共享同一张图，区分度对课程作业足够。

### 2.2 公式实现走 ES `function_score` + `script_score`

按 §4 Q2 决策。单次查询完成，无需 Python 重排。Painless script 拼接三项：

```
score = (1-α) × (w1·BM25_norm + w2·PageRank)
      +  α    × (w3·Semantic × Obscurity)
```

- BM25 归一化：`_score / (_score + 10.0)`，压到 [0,1]，避免不同 query 量纲差异
- Semantic：`(cosineSimilarity(qv, embedding) + 1) / 2`，映射到 [0,1] 防止负贡献
- 字段缺失保护：`doc.containsKey('x') && doc['x'].size() > 0`，否则 Painless 抛异常

### 2.3 模型源换到 ModelScope

HF 官方走代理 SSL 断流（`UNEXPECTED_EOF_WHILE_READING`），hf-mirror 同问题。ModelScope 直连无代理稳定下载（28 min 拉完 pytorch_model.bin）。`model.onnx_data` 失败但 sentence-transformers 走 PyTorch 路径不需要 ONNX。

### 2.4 Embedding 降级路径

`/search?alpha=0.7` 但模型未就绪（path 不存在 / load 失败）时：
- `get_embedder()` 返回 None
- search router 不生成 query_vector
- `build_function_score(use_embedding=False)` → script 里 `sem=1.0` 占位
- α 路径退化为 `Obscurity` 加权，仍能拉低过热点

API 重启会重试加载，所以本地下完模型不用动代码。

### 2.5 max-chars=1500 折中

bge-m3 上下文 8192 token (~24k chars)，但 96k 篇 CPU 全编 8k token 估时 8+ 小时。
- 实际语料 p50 body 9602 chars，p99 116k chars
- 截断到 1500 chars（~400 token）：~15 doc/s，96k 篇 ~1h45m
- 损失：长文末尾语义丢失，但 wiki/fandom 通常 lead paragraph 信息密度最高，可接受

## 3. 实跑结果

### 3.1 数据规模

| 指标 | 值 |
|---|---|
| Mongo 总文档 | 96109 |
| ES 已索引 | 96064 |
| 已写 PageRank/Popularity/Obscurity | 96064 |
| 已写 embedding | 持续中（启动 1h 内 ~2100 → 全量预计 ~1h45m 完成） |
| 失败更新（doc 在 Mongo 但 ES 缺） | 45（doc_parser 增量未 reindex；M5 收尾会做） |

### 3.2 PageRank 图统计

| 指标 | 值 |
|---|---|
| 节点 | 96109 |
| 边（去重内链） | 3,731,117 |
| 平均出度 | ~39 |
| 计算耗时（networkx pagerank, α=0.85, tol=1e-6） | ~30 s |
| 总耗时（含两遍扫表 + ES bulk update） | ~5 min |

**Top-5 PageRank（人工 sanity check）**：

| PR | source | title | in-degree |
|---|---|---|---|
| 0.002354 | fandom | Great Britain | 2514 |
| 0.002033 | fandom | Harry Potter | 2009 |
| 0.001560 | wiki | Character (arts) | 720 |
| 0.001445 | wiki | Protagonist | 667 |
| 0.001256 | fandom | Canon | 1491 |

合理——通用词与跨作品中心节点。

### 3.3 Embedding 速度

| 配置 | doc/s | 备注 |
|---|---|---|
| batch=8, max-chars=2000 | 8 | 烟测 20 篇 |
| batch=32, max-chars=2000 | 11 | 烟测 64 篇 |
| **batch=32, max-chars=1500**（生产） | **~15** | 全量预计 1h45m |

### 3.4 排序公式效果（`q=Luffy`）

| α | top-3 title |
|---|---|
| 0 | Luffy, Law / Yamamoto Luffy / Episode of Luffy |
| 0.3 | Luffy's Great Adventure / Luffy-senpai Support Project! ... |
| 0.7 | Luffy's Great Adventure / ... |
| 1.0 | Luffy's Great Adventure / One Piecein Türkiye / ... |

α↑ 时排序明显从 BM25 + PageRank 热门项滑向语义相关但更冷门项，公式分量切换符合预期。

### 3.5 查询延迟（含 script_score，warm，5 次平均）

| α | mean | 备注 |
|---|---|---|
| 0 | ~45 ms | 与 M4 BM25-only 基本同档 |
| 0.3 | ~80 ms（首次 530ms 模型加载） | 第二次起 ~60 ms |
| 0.7 | ~55 ms | |
| 1.0 | ~40 ms | |

script_score 在 96k 文档上的额外开销可忽略（Painless 编译 + JIT 缓存）。

## 4. 已知坑 & 解决记录

| 现象 | 根因 | 解决 |
|---|---|---|
| HF 官方 / hf-mirror 下大文件 SSL `UNEXPECTED_EOF` | 用户本地代理在长连接流式传输上断流 | 换 ModelScope，直连国内 |
| `huggingface-cli not found` | 新版 `huggingface_hub` 改 CLI 为 `hf` | 用 `hf download` |
| `model.onnx_data` 下载失败 | 大文件代理/CDN 不稳 | 忽略，sentence-transformers 走 pytorch_model.bin |
| ES 45 docs 更新失败 | Mongo 端 doc_parser 新增 45 篇 ES 未 reindex | 收尾时 `build_index --recreate` + `pagerank` 再跑一次 |
| Painless `doc['x'].value` 异常 | 字段值缺失时直接访问会抛 | 全部加 `containsKey + size()>0` 守护 |
| uv install hardlink warning | venv 在 `/mnt/d/`，cache 在 `~/.cache/`，跨文件系统 | `export UV_LINK_MODE=copy` 关警告 |
| Docker Desktop WSL 集成意外断开 | WSL 重启 / Docker Desktop 偏好刷新 | Windows 端重启 Docker Desktop |

## 5. 推迟到 M6+ 的项

- **β · PersonalBoost**：用户档案 + click_history（M6）
- **联想 / 发散度 slider UI**：M7 前端 + completion suggester / ANN
- **knn 召回**（取代当前 script_score 全表扫）：α 高时改用 ES `knn` query 召回 + script_score 重排，提升大规模性能
- **PageRank 增量更新**：现在是全量重算，M6+ 加 `_update_by_query` 增量
- **Obscurity 重定义**：仅用 in-degree 偏简陋；M6 可叠加 source-aware 权重（fandom 角色页 vs reddit 帖）

## 6. 端到端冒烟脚本

```bash
# 0. 基础设施 + 自检
docker compose up -d
python -m indexer.audit --strict

# 1. 网页索引（M4 阶段产物，无变化）
python -m indexer.build_index --recreate

# 2. PageRank + Popularity + Obscurity 离线计算 + 回写 ES
python -m indexer.pagerank

# 3. bge-m3 编码 + 回写 ES（可中断 / 续传）
export BGE_M3_MODEL_PATH=/home/lumine/model/bge-m3
python -m indexer.embed --batch 32 --max-chars 1500

# 4. 启 API（α slider 已就绪）
uvicorn api.main:app --port 8000

# 5. 公式分量验证
BASE=http://127.0.0.1:8000
for a in 0 0.3 0.7 1.0; do
    echo "--- alpha=$a ---"
    curl -sS "$BASE/search?q=Luffy&alpha=$a&size=3" | jq '.hits[]|{score,title}'
done
```

## 7. 下一步（衔接 M6）

按 `design.md §7 — M6 用户系统 + 个性化 + 发散度滑杆`：

- [ ] `api/routers/auth.py`：注册 / 登录 / JWT
- [ ] Mongo `users` 集合：interests、click_history、preferred_sources
- [ ] `api/personalization.py`：β·PersonalBoost 接入公式
- [ ] α slider 与 β 共存的 UI 抽象（这里只是 API 端的接口，UI 在 M7）
- [ ] 个性化推荐 / 联想（completion suggester + ANN 召回）
