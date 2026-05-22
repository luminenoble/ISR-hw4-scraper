# Sec.4 ES 索引 + 6 种查询全部跑通（M4 阶段）

> 对应里程碑：`design.md §7 — M4 ES 索引建好，6 种查询全部跑通`
> 完成日期：2026-05-22
> 上游依赖：`docs/sec3-summary.md`（96020 网页就位 + 质量门已识别）

## 1. 交付物清单

| 路径 | 性质 | 作用 |
|---|---|---|
| `indexer/audit.py` | 新增 | 导库前自检（sec3 §3.2 6 项红线固化为脚本） |
| `indexer/es_mapping.json` | 新增 | ES 多字段 + 多分析器 mapping |
| `indexer/build_index.py` | 新增 | Mongo → ES streaming_bulk，支持断点 / recreate |
| `parser/doc_parser.py` | 新增 | Tika 文档解析，从已抓 anchors 筛 .pdf |
| `api/main.py` | 新增 | FastAPI 入口（lifespan + CORS） |
| `api/deps.py` | 新增 | ES / Mongo client 单例 + lifespan |
| `api/query_parser.py` | 新增 | 查询字符串解析（短语 / 通配 / 字段前缀） |
| `api/routers/search.py` | 新增 | 站内 / 文档 / 短语 / 通配 4 路统一入口 |
| `api/routers/snapshot.py` | 新增 | `/snapshot/{doc_id}` 读 gzip（HTML/PDF 自适应 MIME） |
| `api/routers/log.py` | 新增 | 查询日志读取（写在 search 里） |
| `api/schemas.py` | 新增 | Hit / SearchResponse / LogEntry |
| `tests/test_audit.py` | 新增 | 4 个 case |
| `tests/test_query_parser.py` | 新增 | 11 个 case |
| `crawler/isr_crawler/utils.py` | 修改 | `snapshot_path_for` 加 `ext` 参数支持 pdf.gz |
| `pyproject.toml` | 修改 | 加 httpx / tqdm / elasticsearch / fastapi / uvicorn |
| Mongo `raw_pages` | 数据 | +44 `source=document`，总数 96064 |
| ES `isr_pages` | 数据 | 96064 文档已索引 |

## 2. 关键决策

### 2.1 分词器从 smartcn 退回到内置 cjk

**计划**：装 `analysis-smartcn` 插件，title/anchors/body 走 `standard + english + smartcn` 三分析器多字段。
**实际**：WSL2 容器无法解析 `artifacts.elastic.co`（宿主走 http_proxy:2334，docker 网络穿透失败）。
**改方案**：用 ES 内置 `cjk` 分析器（双字 bigram，零插件），加 `english` 处理英文形态。
**影响**：中文召回质量低于 smartcn，但本项目语料 90%+ 英文（reddit/fandom/wiki en），可接受。
**遗留**：`Dockerfile.es` 已删；如后续要换回 smartcn，恢复 build 段 + 离线下载 zip 即可。

### 2.2 多字段命名与权重

```
title (standard)         → boost 3
title.en (english)       → boost 3   # 英文还原词形
title.cjk (cjk bigram)   → boost 3   # 中文 fallback
anchors_text (standard)  → boost 2   # anchors[].text 拍平后入索引
body (standard)          → boost 1
```

`anchors_text` 是把 Mongo 端 `anchors: [{text, to}]` 的所有 `text` 用空格 join 后入的 text 字段。锚文本"用更短文本概括目标页"的特性使其权重应高于 body，体现 HITS 思想的工程化简化。

### 2.3 `pagerank` / `obscurity` / `embedding` 字段留空位

按既定决策 PageRank 留 M5：mapping 中字段已建（float / dense_vector dims=1024），值缺省为 0 / null。M5 写回时无需 reindex，走 `_update_by_query` 即可。

### 2.4 文档源走 anchors 筛 .pdf

**候选**：扫 raw_pages 全表 `url` + `anchors[].to`，正则 `\.pdf(\?|#|&|$)` 匹配，得 4491 unique URL。
**洗牌**：字典序首部全是数字 IP / 已停服域名，随机化（seed=42）+ 偏好 https。
**下载**：httpx 15s 超时，校验 `%PDF` 魔术字节，丢弃 HTML 假冒。
**Tika**：PUT `/tika` 拿纯文本 + PUT `/meta` 拿 dc:title；客户端 `trust_env=False` 绕本地 http_proxy（关键！否则全 502）。
**结果**：限 200 抽样，跑到 108 时手动 Ctrl-C，入库 44 篇（~40% 成功率，多数失败为 SSL EOF / 死链）。

### 2.5 查询日志在 search 端落

每次 `/search` 命中后异步插 `query_log{user_id, query, kind, filters, ts, total, result_ids}`。
索引 `(user_id, ts desc)` 建在 lifespan 里。`/logs` 路由只读，不写。

## 3. 实跑结果

### 3.1 数据规模

| 维度 | 数 |
|---|---|
| Mongo 总文档 | 96064 |
| ES `isr_pages` 文档数 | 96064 |
| document 来源 | 44 |
| reddit / wiki / fandom | 58500 / 19661 / 17859 |

audit 全 0 红线（URL / title / doc_id / snapshot_path / 快照文件 / 跨源冲突）。

### 3.2 索引耗时

全量 96k bulk_size=500：**1m52s**（峰值 ~8500 doc/s，平均 ~860 doc/s 含 ES merge 时段）。

### 3.3 6 种查询验证（curl 实测）

| 编号 | 样例查询 | kind | total hits | 备注 |
|---|---|---|---|---|
| 站内 | `q=Harry Potter` | match | 10000+（capped）| multi_match cross language |
| 文档 | `q=*&source=document` | wildcard+filter | 44 | source 过滤生效 |
| 短语 | `q="monkey d luffy"` | phrase | 4689 | match_phrase 比无引号召回更精 |
| 通配 | `q=luff*` | wildcard | 6206 | query_string analyze_wildcard |
| 日志 | `GET /logs?limit=5` | - | 4 | 上述 4 次查询全部留痕 |
| 快照 | `GET /snapshot/{doc_id}` | - | - | HTML 55KB / PDF 6.2MB 双 MIME 通过 |

### 3.4 查询延迟（warm，10 次平均）

| 查询 | mean | 备注 |
|---|---|---|
| `Harry Potter` (match) | 56–200 ms | 第一次 cold 200ms，warm 56ms |
| `luffy gear` (match) | ~37 ms | |
| `"strawhat pirates"` (phrase) | ~13 ms | 倒排 positions 加持 |
| `naru*` (wildcard) | ~25 ms | |

满足课程作业"可用"标准；后续 M5 加 PageRank 重排可能小幅上升。

## 4. 已知坑 & 解决记录

| 现象 | 根因 | 解决 |
|---|---|---|
| `urlparse` 抛 `ValueError: netloc contains invalid characters under NFKC normalization` | anchors 内有日文 wiki URL 含未 punycode 主机名 | try/except 兜底，对原串再做一次 regex |
| Tika PUT 全 502 | WSL 全局 `http_proxy=127.0.0.1:2334`，httpx 走 proxy 时被改写 | `httpx.Client(trust_env=False)` 仅 Tika 客户端绕 proxy |
| smartcn 插件装不上 | 容器无法解析 `artifacts.elastic.co`（DNS / proxy 联合阻断） | 改用内置 `cjk` 分析器；docker-compose 回滚到 image: |
| bulk 速度第 75k 处骤降（7800→1500 doc/s） | ES segment merge 阻塞 | 不动；总耗时仍可接受。M5 起索引前可 `index.refresh_interval=-1` 优化 |
| `_cat/indices?v` shell 解析失败 | zsh `?` 是 glob | 用 `"http://...?v"` 双引号包住或 setopt no_nomatch |
| `pip` 装不进 venv | `which pip` 落 `/usr/bin/pip`，venv 缺 pip | 用 `uv pip install` 顶上，无需重建 venv |

## 5. 推迟到 M5+ 的项

- **PageRank 离线计算**：构图（节点=doc_id，边=anchors[].to 解析后的内链）→ networkx → `_update_by_query` 写 `pagerank` 字段
- **bge-m3 embedding**：批量编码 96k body → 写 `embedding` 字段；ES `knn` 召回与 BM25 hybrid 排序
- **排序公式**：`α·SemanticSim·Obscurity + (1-α)·(BM25 + PageRank)` 实际接线
- **个性化**：用户表 + click_history + `PersonalBoost`
- **联想 / 发散度 slider**：completion suggester + ANN 50 最近邻
- **前端**：Streamlit / Vue
- **infobox 字段抽取**：现在统一空 `{}`，没用上 flattened 字段；wiki/fandom 解析 wikitext 后回填
- **跨源 dedup**：URL 规范化 pipeline（M3 §6 也提到的）

## 6. 端到端冒烟脚本（已验证可复现）

```bash
# 1. 起基础设施
docker compose up -d

# 2. 自检（红线全 0 才继续）
python -m indexer.audit --strict

# 3. 抓 PDF（可选；不跑也不影响 6 种查询全跑通）
python -m parser.doc_parser --limit 200 --delay 0.5

# 4. 建索引（首次或重灌）
python -m indexer.build_index --recreate --batch 500

# 5. 启 API
uvicorn api.main:app --port 8000

# 6. 6 路冒烟
BASE=http://127.0.0.1:8000
curl -sS "$BASE/health"
curl -sS "$BASE/search?q=Harry+Potter&size=3"
curl -sS "$BASE/search?q=harry&source=document&size=3"
curl -sS '$BASE/search?q="monkey d luffy"&size=3'
curl -sS "$BASE/search?q=luff*&size=3"
curl -sS "$BASE/logs?limit=5"
curl -sS "$BASE/snapshot/<doc_id>" -o /tmp/snap.html
```

## 7. 下一步（衔接 M5）

按 `design.md §7 — M5 PageRank + embedding + 排序公式整合`：

- [ ] `indexer/pagerank.py`：构图 + networkx + `_update_by_query`
- [ ] `indexer/embed.py`：bge-m3 批量编码（CPU 也跑得动，分批 32 / batch）
- [ ] `api/ranking.py`：把排序公式接到 search router，新增 `alpha` 查询参数
- [ ] 端到端 latency 重测（含 knn 召回）
