# ISR-scraper · 同人创作角色背景检索引擎

> 信息存储与检索（ISR）课程作业 · 面向**小说同人创作**的垂直搜索引擎
> 数据源 Fandom / Wikipedia / Reddit / 文档 · 索引 96,109 文档 · 全栈 0 元自托管
> 设计文档：[`design.md`](./design.md) · 协作上下文：[`CLAUDE.md`](./CLAUDE.md)

---

## 1. 是什么

同人作者写一个角色需要的"背景信息"散落在三个层次：

1. **官方权威** —— Wikipedia / Fandom 上的人物条目（canon）
2. **民间二创** —— Reddit 上的 fan theory / AU 设定（fanon）
3. **结构化文档** —— PDF / docx 形式的研究报告与同人征文集

通用搜索不能在这三层间做精细切换。ISR-scraper 把它们抓回本地、统一索引，提供一根 **"发散度 slider α"** 让用户在「官方权威 ↔ 民间二创」连续光谱上自由滑动；再叠一个 **"个性化权重 β"** 让登录用户长期点 reddit 的人自然在 reddit 内容上拿到加分。

| 能力 | 实现 |
|---|---|
| 站内 / 文档 / 短语 / 通配 / 日志 / 快照 6 种查询 | FastAPI + ES multi_match / match_phrase / query_string / Mongo log / gzip |
| 排序公式 `(1-α)·[BM25+PR] + α·[Sem·Obs] + β·PB` | ES function_score + Painless script |
| 个性化 source/tag/click 三分量 PersonalBoost | argon2 + JWT + Mongo users 集合 |
| 语义召回 | bge-m3 1024-dim dense_vector（cosine） |
| 搜索联想（前缀 + kNN 语义混合） | Mongo n-gram + ES knn，前端 α 实时切混合比 |
| Vue3 档案馆风格 UI | 5 页 + 3 组件，gzip 50KB main bundle，无 UI 库 |

---

## 2. 架构总览

```
┌───────────────────────────────────────────────────────┐
│  Web UI (Vue3 + Vite)   /search /detail /me /log      │
└────────────────────┬──────────────────────────────────┘
                     │  /api/*
┌────────────────────▼──────────────────────────────────┐
│  FastAPI 服务（18 端点）                               │
│  search · suggest · auth · feedback · log · snapshot  │
│  doc · ranking 公式 · PersonalBoost                   │
└─────┬───────────────┬───────────────┬─────────────────┘
      │               │               │
┌─────▼──────┐ ┌──────▼──────┐ ┌──────▼──────────────┐
│ Elastic-   │ │ MongoDB     │ │ data/snapshots/      │
│ search     │ │ raw_pages   │ │ gzip HTML / PDF     │
│ 96,109 doc │ │ query_log   │ │ ~3.2 GB             │
│ + 1024-dim │ │ users       │ │                     │
│ embedding  │ │ events      │ │                     │
└────────────┘ └─────────────┘ └─────────────────────┘
      ▲              ▲                ▲
      │ 离线任务 ────┴────────────────┘
┌─────┴──────────────────────────────────────────────────┐
│  Scrapy spiders（fandom/wiki/reddit/ao3）              │
│  Tika 文档解析 · PageRank · bge-m3 embedding · audit  │
└────────────────────────────────────────────────────────┘
```

完整设计见 [`design.md`](./design.md)。

---

## 3. 数据规模

| source | 文档数 | embedding 覆盖 |
|---|---:|---:|
| reddit | 58,500 | 100% |
| wiki | 19,661 | 100% |
| fandom | 17,859 | 100% |
| document（PDF/docx） | 89 | 100% |
| **合计** | **96,109** | **100%** |

- PageRank：96,109 节点 / 3.73M 边，离线 networkx 计算后回写 ES
- 网页快照：每条文档 `data/snapshots/ab/cd/<doc_id>.html.gz`
- 索引大小：~5.8 GB（含 embedding）

---

## 4. 快速启动

### 4.1 前置依赖

- Docker Desktop（Mac/Win）或 dockerd（Linux）—— 起 ES + Mongo + Tika
- Python ≥ 3.11
- Node.js ≥ 20 （前端 dev/build）
- 可选：`bge-m3` 模型本地 checkpoint（无则 α 路径自动降级为 BM25×Obscurity）

### 4.2 启动基础设施

```bash
docker compose up -d
# 等待 ES 健康（10–30s）
curl -s http://localhost:9200/_cluster/health
```

### 4.3 后端

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 可选：指定本地 bge-m3 模型路径
export BGE_M3_MODEL_PATH=/path/to/bge-m3

uvicorn api.main:app --port 8000
# → http://127.0.0.1:8000/health  应返回 {"ok": true, "doc_count": 96109}
```

### 4.4 前端

```bash
cd frontend
npm install
npm run dev                       # vite dev server: http://127.0.0.1:5173
# 或构建：
npm run build && npx vite preview --port 5173
```

打开 <http://127.0.0.1:5173>：

1. 顶栏 **登录 → 注册** 走两步式注册（账号 + 冷启动偏好）
2. 进入 `/search`：搜索框输入 `Luffy`，看联想下拉
3. 展开"调节面板"拖 **α slider**：左端权威、右端二创
4. 登录后拖 **β slider** 看个性化加权效果
5. 点结果卡上的「详情」或「快照」（双埋点：events + click 反馈链路）

---

## 5. 跑评测

```bash
source .venv/bin/activate
# 后端必须在跑（评测脚本走 HTTP API）

python eval/eval_alpha.py            # → reports/eval_alpha.md
python eval/eval_queries.py          # → reports/eval_queries.md
python eval/eval_personalization.py  # → reports/eval_personalization.md
```

### 评测亮点（M8 实测）

- **α 工作正常**：obscurity 从 α=0 的 0.66 单调爬升到 α=1 的 1.0；α=0 与 α=1 的 top-10 完全不重叠（Jaccard=0）
- **β 工作正常**：偏 reddit 用户在 β=1.5 时 top-10 reddit 占比从 48% → 93%，6/10 query 的 top1 漂移
- **6 种查询全跑通**：服务端 took 33–57ms，端到端 40–120ms；快照 gzip 平均 ~55KB
- **完整 case study 与失败分析**：见 [`docs/sec8-summary.md`](./docs/sec8-summary.md)

---

## 6. 跑测试

```bash
source .venv/bin/activate
pytest tests/ -q --no-cov
# 62 passed in 6.5s
```

测试覆盖：query_parser / ranking / suggest / 个性化更新 / auth / audit / `/doc/{id}` 路由（mock ES）等核心模块。

---

## 7. 目录结构

```
ISR-scraper/
├── api/                FastAPI 服务（路由 + ranking + 个性化）
│   └── routers/        search / doc / auth / feedback / log / suggest / snapshot
├── crawler/            Scrapy 项目（fandom / wiki / reddit spider）
├── indexer/            build_index / pagerank / embed / audit
├── parser/             Tika 文档解析
├── frontend/           Vue3 + Vite（5 页 + 3 组件 + telemetry）
├── eval/               M8 评测脚本（α / 6 query / 个性化）
├── reports/            评测产出（Markdown + JSON）
├── docs/               阶段总结 sec1–sec8 + 设计文档 + Android 方案
├── data/               snapshots/（gzip HTML）+ graph/（PageRank 中间结果）
├── tests/              pytest 套件
├── design.md           架构设计文档（single source of truth）
├── CLAUDE.md           协作上下文
└── docker-compose.yml  ES + Mongo + Tika
```

---

## 8. 阶段交付（design.md §7 里程碑）

| 阶段 | 内容 | 文档 |
|---|---|---|
| M1 | 基础设施 + Scrapy 骨架 | [sec1](./docs/sec1-summary.md) |
| M2 | Fandom + Wiki spider | [sec2](./docs/sec2-summary.md) |
| M3 | Reddit + Tika 文档解析 | [sec3](./docs/sec3-summary.md) |
| M4 | ES 索引 + 6 种查询 | [sec4](./docs/sec4-summary.md) |
| M5 | PageRank + embedding + 排序公式 | [sec5](./docs/sec5-summary.md) |
| M6 | 用户系统 + 个性化 + 联想 | [sec6](./docs/sec6-summary.md) |
| M7 | Vue3 前端 + 移动端预埋 | [sec7](./docs/sec7-summary.md) |
| M8 | 联调 / 评测 / 报告 | [sec8](./docs/sec8-summary.md) |

---

## 9. 合规与风险红线

- 严格遵守 robots.txt；User-Agent 含联系方式
- Fandom / Wiki / Reddit 全部走官方 API，零代理成本
- 不爬取需要登录的私密内容、不绕 CAPTCHA
- 数据仅用于本课程作业，**不公开发布原始抓取数据**

---

## 10. License

课程作业，仅供学习交流。第三方依赖各自遵循其上游 License（ES / Tika / bge-m3 / Vue 等）。
