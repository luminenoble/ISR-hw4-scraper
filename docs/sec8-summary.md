# Sec.8 联调 / 测试 / 评测报告（M8 阶段）

> 对应里程碑：`design.md §7 — M8 联调 / 测试 / 评测报告`
> 完成日期：2026-05-24
> 上游依赖：`docs/sec7-summary.md`（Vue3 前端 + 联想 + α/β slider）

## 1. 交付物清单

### 后端补全（M8-1）

| 路径 | 性质 | 作用 |
|---|---|---|
| `api/routers/doc.py` | 新增 | `GET /doc/{id}`：详情页正文 + 全字段元数据（无 embedding/snapshot_path 大字段） |
| `api/schemas.py` | 修改 | 加 `DocDetail` 响应模型 |
| `api/main.py` | 修改 | 挂载 `doc.router` |
| `tests/test_doc.py` | 新增 | TestClient + ES mock 覆盖：200/404/截断/snapshot/embedding 标记 |

### 前端补全（M8-2）

| 路径 | 性质 | 作用 |
|---|---|---|
| `frontend/src/lib/api.ts` | 修改 | 加 `DocDetail` 类型 + `getDoc()` 客户端 |
| `frontend/src/pages/Detail.vue` | 修改 | 接 `/doc/{id}` 渲染信息框 + 正文 + pagerank/obscurity 等排序信号；route 变化自动重载 |

### 评测脚本（M8-3）

| 路径 | 性质 | 作用 |
|---|---|---|
| `eval/common.py` | 新增 | ES/.env 加载 + 10 条样本 query + Jaccard / RBO 工具 |
| `eval/eval_alpha.py` | 新增 | α=0/0.3/0.7/1.0 四档对比：source 分布 + obscurity + pagerank + 档间重叠 |
| `eval/eval_queries.py` | 新增 | 6 种查询 case study（站内/文档/短语/通配/日志/快照） |
| `eval/eval_personalization.py` | 新增 | β=0/1.5/3.0 三档对比：构造偏 reddit/fanon 虚拟用户 |

### 报告产出

| 路径 | 内容 |
|---|---|
| `reports/eval_alpha.md` + `.json` | α 评测全表 |
| `reports/eval_queries.md` | 6 种查询 case study |
| `reports/eval_personalization.md` | 个性化排序评测 |
| `docs/sec8-summary.md` | 本文 |
| `README.md` | 项目概要 + 快速启动 + 评测亮点（根目录新建） |

## 2. 关键决策

### 2.1 `/doc/{id}` 走 ES `_id` 直查，不查 Mongo

详情页只要：title/body/infobox/pagerank/obscurity 等已在 ES 索引上的字段。Mongo `raw_pages` 同份字段但要走 url→doc_id 二次解析，再多一跳。ES `_id == doc_id`，`get(index, id)` O(1)，无需走查询语义。

`snapshot_path` 字段在 mapping 里有但 `index: false, doc_values: false`，`_source` 仍能拿到，用来填 `has_snapshot` 布尔，前端据此决定是否显示「网页快照」按钮——比 HEAD 一次 `/snapshot/{doc_id}` 划算。

`embedding` 字段 1024 维 / ~4KB / 条，明显不能回前端。改成单独发一次 `term + exists` 探针（带 `size: 0`），只回布尔。

### 2.2 body 默认裁 8000 字符

reddit 长帖 / wiki 长条目动辄 5–30KB；详情页只用于"快速预览 + 决定是否点快照"，8000 字符（约 1300 中文 / 2000 英文 word）能撑住 lede + 主要段落。前端可传 `?body_max=0` 取完整正文，但当前 UI 不暴露这个参数。

### 2.3 评测脚本走 HTTP API 而非 import 函数

两种写法各有所长：
- import：跳过 HTTP + Pydantic 序列化，跑得快、不依赖 uvicorn
- HTTP：把 query_parser + embedder lazy load + log 写入 + function_score + highlight 整条链路都跑通

选择 HTTP，因为评测目的就是"线上行为快照"。代价：`uvicorn` 必须在跑，eval 脚本 readme 里写明。

httpx Client 全部加 `trust_env=False` 显式禁用代理——WSL 下系统 `HTTP_PROXY=http://127.0.0.1:2334` 会把 localhost 也走代理触发 502，已在 `eval_*.py` 三个脚本统一处理。

### 2.4 没用 NDCG/MRR

NDCG/MRR 需要金标签注。本项目没有标注数据集，硬给 query 标"相关 doc_id"主观偏差大。改用 **行为分布指标**：
- α 评测：top-10 的 source 分布、平均 obscurity、档间 Jaccard / RBO
- β 评测：top-10 中匹配用户偏好 source 的占比、top1 是否漂移

这些指标对"发散度/个性化"的物理意义比 NDCG 直接——能直接证明 α↑ 会让稀有度↑、β↑ 会让偏好 source 占比↑。

### 2.5 RBO 选 p=0.9

`rbo(a, b, p=0.9)` 中 p=0.9 等价于"考虑前 ~10 名的有序重叠"。比 Kendall 更适合长 ranking 头部对比；本项目 top-K=10，p=0.9 刚好把权重压在 top-10 内。

## 3. 评测结果摘要

### 3.1 α 发散度评测（reports/eval_alpha.md）

| α | avg obscurity | avg pagerank | 主导 source |
|---|---|---|---|
| 0.0 | **0.6559** | 4.71e-05 | reddit(48), wiki(40) |
| 0.3 | 0.9728 | 4.60e-06 | reddit(78) |
| 0.7 | 1.0000 | 4.14e-06 | reddit(80) |
| 1.0 | **1.0000** | 4.14e-06 | **wiki(70)** |

档间重叠（top-10）：

| 对比 | Jaccard | RBO |
|---|---|---|
| α0↔α0.3 | 0.448 | 0.365 |
| α0.3↔α0.7 | 0.899 | 0.614 |
| α0.7↔α1.0 | 0.018 | 0.007 |
| α0↔α1.0 | **0.000** | **0.000** |

**结论**：

1. **α 的物理意义符合设计**：obscurity 从 0.66 单调爬升到 1.0，证明 α↑ 真的把"稀有冷门"提到前面
2. **0↔1 完全不重叠**：纯 BM25+PageRank 路线和纯语义路线 top-10 零交集，说明两路确实跑出了不同信号
3. **0.3↔0.7 高重叠**（0.899）反而说明中间区段过度黏合——可以考虑改 score 的权重曲线（如非线性 α）来扩大中间分辨力，留 M9（如有）
4. α=1.0 时 wiki 反超 reddit（70:80→70:0），是 obscurity 倍乘把 wiki 短条目（多为冷门小说人物）的语义近邻拉到了 reddit 前面

### 3.2 个性化评测（reports/eval_personalization.md）

虚拟用户：`preferred_sources={reddit:1.0, wiki:0.0, fandom:0.0}`, `preferred_tag_weights={fanon:1.0}`

| β | 平均 reddit 占比（top-10） | top1 漂移次数 |
|---|---|---|
| 0.0 | 48% | 0/10 |
| 1.5 | **93%** | 6/10 |
| 3.0 | 93% | 6/10 |

**结论**：

1. β=1.5 已让 reddit 占比从 48% → 93%，**6/10 query 的 top1 都换了**——说明 PersonalBoost script 真的在按 source/tag 加分
2. β=1.5 与 β=3.0 同分（93%）：因为 reddit 已经占满 top-10，再加 β 也只是把已有的 reddit 再往上排，对 source 分布没影响。`Luffy/Genshin Impact` 这种 fandom 主导 query 的 reddit 占比从 0% → 100% 是最直接的证据
3. **隐藏前置条件**：URL `?beta=X` 要生效，必须用户 `default_beta > 0`。`boost_params_for` 在 `default_beta == 0` 时直接返回 `{beta: 0}`，pref_sources/tags 不会回填，导致后续 URL beta 即便非零也走不进 script_score 的 personal_src 分支。**M9 前应在 search router 把这个分支改成"用户登录 → 总是回填 pref/tag，让 URL beta 决定权重"**，否则交互上很反直觉。

### 3.3 六种查询 case study（reports/eval_queries.md）

| 查询类型 | 实例 | kind | took_ms 服务端 | total | 备注 |
|---|---|---|---|---|---|
| 2.3.1 站内 | `Luffy strawhat` | match | 34 | 6167 | multi_match 跨 title/anchors/body |
| 2.3.2 文档 | `character + source:document` | match | 33 | **44** | source=document filter，命中 PDF/docx |
| 2.3.3 短语 | `"alternate universe"` | phrase | 57 | **886** vs 10000 loose | 引号触发 match_phrase，命中率 8.86% |
| 2.3.4 通配 | `naru*` | wildcard | 55 | 718 | query_string analyze_wildcard |
| 2.3.5 日志 | 注册→2 次搜索→读 /logs/me | - | - | **logged=2** ✓ | Mongo query_log 集合 |
| 2.3.6 快照 | 任一搜索结果 doc_id | - | - | **55195 B HTML** ✓ | gzip 解压 + text/html |

**结论**：六种查询全部跑通；短语查询通过 phrase/loose 命中数比例（0.0886）证明 `match_phrase` 真的在用 positions 严格匹配，区别于无引号的 token 查询。

## 4. embedding 收尾确认

| source | 文档数 | 有 embedding |
|---|---|---|
| reddit | 58500 | **58500 (100%)** |
| wiki | 19661 | **19661 (100%)** |
| fandom | 17859 | **17859 (100%)** |
| document | 89 | **89 (100%)** |
| **合计** | **96109** | **96109 (100%)** |

bge-m3 全量回写完成。背景任务从 M7 启动时 ~43% / ETA 1h40m → 已完成。

## 5. 数据规模总览

| 指标 | 数值 |
|---|---|
| ES 索引文档数 | 96,109 |
| 平均 pagerank | 1.04e-05 |
| 平均 obscurity | 0.804 |
| 平均 popularity | 38.82 |
| Mongo 测试集合 | raw_pages / query_log / users / events |
| 快照体积（gzip） | ~3.2 GB（data/snapshots/） |
| embedding 维度 | 1024（bge-m3） |
| API 端点数 | 18（含 /doc/{id}） |

## 6. 端到端冒烟

```bash
# 起基础设施
docker compose up -d

# 起后端
source .venv/bin/activate
export BGE_M3_MODEL_PATH=/home/lumine/model/bge-m3
uvicorn api.main:app --port 8000 &

# 起前端
cd frontend && npm run dev          # http://127.0.0.1:5173

# 跑评测
cd ..
python eval/eval_alpha.py           # → reports/eval_alpha.md
python eval/eval_queries.py         # → reports/eval_queries.md
python eval/eval_personalization.py # → reports/eval_personalization.md

# 跑单测
pytest tests/ -q --no-cov           # 62 passed in 6.5s
```

## 7. 已知遗留 & 后续

| 项 | 状态 | 优先级 |
|---|---|---|
| `/doc/{id}` body 默认 8000 字符截断 | 已实现 | - |
| URL `?beta=X` 在 user.default_beta=0 时不生效 | **M9 已修**：`boost_params_for` 不再短路，pref/tag/click 一律回填，beta 由 search router 决定 | ✓ |
| 中间 α（0.3↔0.7）档间区分度低 | **M9 已修**：search router 加 `_alpha_curve` 余弦映射，中段 Jaccard 0.899→0.440 | ✓ |
| 多选 source filter（terms query） | M7 推迟 | 视用户反馈 |
| 离线 PWA 缓存 | M7 推迟 | 低 |

### 7.1 M9 修补：boost 分支语义

`api/personalization.py:boost_params_for` 不再用 `default_beta<=0` 短路，无论 beta 值多大都把 pref_sources / pref_tags / click_set 回填。`api/routers/search.py` 的 boost 装配简化为：

```python
pb = boost_params_for(current_user)
pb["beta"] = beta if current_user else 0.0
if pb["beta"] <= 0:
    pb = {"beta": 0.0}        # 关闭个性化，免 script 误开 personal_src
```

**回归验证**：注册 `default_beta=0` + `preferred_sources={reddit:1.0}` 用户，跑 `?beta=3.0` 查 `Luffy`：

| 状态 | reddit / top-10 | top1 |
|---|---|---|
| M8 旧版 | 0/10 | `'Luffy, Law'` (fandom) |
| M9 修后 | **10/10** | `"One Piece Fanfics Where Luffy/Straw Hats Travel..."` (reddit) |

新增固化单测 `tests/test_personalization.py:test_boost_params_zero_beta_still_returns_prefs` + `test_boost_params_keeps_prefs_when_default_beta_zero`。

### 7.2 M9 修补：α 曲线（方案 A 余弦再映射）

`api/routers/search.py` 加 `_alpha_curve(α) = 0.5·(1 − cos(π·α))`：

- 边界保持：`eff(0)=0, eff(0.5)=0.5, eff(1)=1`
- 中点斜率 = π/2 ≈ 1.57，比线性多 57%

UI 仍传原始 α∈[0,1]，script_score 收到的是 effective_alpha。同时 `query_log` 多记一列 `effective_alpha` 方便回溯。

**回归验证**（reports/eval_alpha.md，10 个 query × 4 档 × top-10）：

| 对比 | M8 (线性) | M9 (余弦) | 含义 |
|---|---|---|---|
| α0↔α0.3 | 0.448 | 0.410 | 略降，可接受 |
| **α0.3↔α0.7** | **0.899** | **0.440** | **中段从黏合到 ~56% 结果变化** |
| α0.7↔α1.0 | 0.018 | 0.343 | 高段从过陡变平滑（曲线把斜率移到中段的必然代价） |
| α0↔α1.0 | 0.000 | 0.049 | 两端依然几乎不重叠 |

副作用：α=0.7 的 effective ≈ 0.65（不再是 0.7），高段"纯语义体验"略弱化。若日后想找回，方案 B（量纲对齐）+ 双 sigmoid 曲线可二次迭代。

新增 6 条单测（`tests/test_ranking.py:test_alpha_curve_*`）固化曲线性质：保端点、过中点 0.5、单调、中段被拉开、越界 clamp、公式一致。

测试套件总数：68 passed（M8 时 62 + 新增 6）。

## 8. 阶段性收束

至此，design.md §7 的 M1–M8 八个里程碑全部交付：

- M1 基础设施 ✓
- M2 Fandom + Wiki spider ✓
- M3 Reddit + Tika ✓（96109 文档）
- M4 ES 索引 + 6 种查询 ✓
- M5 PageRank + embedding + 排序公式 ✓
- M6 用户系统 + 个性化 ✓
- M7 Vue3 前端 + 联想 + 快照页 + 日志展示 ✓
- M8 联调 + 评测 ✓（本文）

下一步（若有 M9）：
- 修 boost beta 分支语义
- 改进 α 曲线分辨力
- 加 NDCG/MRR 评测（先需要少量人工标注）
- Inkite Android 端落地（设计已就绪：`docs/android-integration.md`）
