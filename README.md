# ISR-scraper · 同人创作角色背景检索引擎

> 面向**小说同人创作**的垂直搜索引擎
> 数据源 Fandom / Wikipedia / Reddit / 文档 / AO3 · 索引规模 10 万级 · 全栈 0 元自托管

---

## 1. 项目简介

同人作者写一个角色需要的"背景信息"散落在三个层次：

1. **官方权威** —— Wikipedia / Fandom 上的人物条目（canon）
2. **民间二创** —— Reddit 上的 fan theory / AU 设定（fanon）
3. **结构化文档** —— PDF / docx 形式的研究报告与同人征文集

通用搜索不能在这三层间做精细切换。本项目把它们抓回本地、统一索引，提供一根 **"发散度 slider α"** 让用户在「官方权威 ↔ 民间二创」连续光谱上自由滑动；再叠一个 **"个性化权重 β"** 让登录用户的长期点击行为反馈到排序中。

| 能力 | 实现 |
|---|---|
| 站内 / 文档 / 短语 / 通配 / 日志 / 快照 6 种查询 | FastAPI + ES multi_match / match_phrase / query_string / Mongo log / gzip |
| 排序公式 `(1-α)·[BM25+PR] + α·[Sem·Obs] + β·PB` | ES function_score + Painless script |
| 个性化 source/tag/click 三分量 PersonalBoost | argon2 + JWT + Mongo users 集合 |
| 语义召回 | bge-m3 1024-dim dense_vector（cosine） |
| 搜索联想（前缀 + kNN 语义混合） | Mongo n-gram + ES knn，前端 α 实时切混合比 |
| Vue3 档案馆风格 UI | 5 页 + 3 组件，gzip ~50KB main bundle，无 UI 库 |

详细架构见 [`design.md`](./design.md)。

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
│ (索引层)   │ │ query_log   │ │                     │
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

---

## 3. 目录结构

```
ISR-scraper/
├── api/                FastAPI 服务（路由 + ranking + 个性化）
│   └── routers/        search / doc / auth / feedback / log / suggest / snapshot
├── crawler/            Scrapy 项目（fandom / wiki / reddit / ao3 spider）
├── indexer/            build_index / pagerank / embed / audit
├── parser/             Tika 文档解析
├── frontend/           Vue3 + Vite（5 页 + 3 组件 + telemetry）
├── eval/               评测脚本（α / 6 query / 个性化）
├── reports/            评测产出（Markdown + JSON）
├── docs/               设计文档 + 实验报告 + Android 方案
├── data/               snapshots/（gzip HTML）+ graph/（PageRank 中间结果）
├── tests/              pytest 套件
├── design.md           架构设计文档（single source of truth）
└── docker-compose.yml  ES + Mongo + Tika
```

---

## 4. 环境准备

### 4.1 前置依赖

- **Docker Desktop**（Win/Mac）或 dockerd（Linux）—— 起 ES + Mongo + Tika
- **Python ≥ 3.11**
- **Node.js ≥ 20** （前端 dev/build）
- 可选：本地 `bge-m3` 模型 checkpoint（无则 α 路径自动降级为 BM25×Obscurity）

### 4.2 Python 环境

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 4.3 启动基础设施

```bash
docker compose up -d
# 等待 ES 健康（10–30s）
curl -s http://localhost:9200/_cluster/health
```

默认服务端口（可通过 `.env` 覆盖，详见 `docker-compose.yml`）：

| 服务 | 端口 | 凭据 |
|---|---|---|
| Elasticsearch | 9200 | 无 |
| MongoDB | 27017 | isr / isr_dev_pw |
| Tika | 9998 | 无 |

---

## 5. 数据获取（重要）

> 提交包**不含数据**。所有数据需自行抓取。完整流程：抓取 → 入 Mongo → 建 ES 索引 → 计算 PageRank → 写入 embedding。

### 5.1 抓取 Fandom

`fandom` spider 通过 MediaWiki API 拉取指定 wiki 的角色/剧情条目。

```bash
cd crawler

# 单 wiki 示例：抓 onepiece.fandom.com 英文版 1 万条
scrapy crawl fandom -a wiki=onepiece -a lang=en -a limit=10000

# 切换 wiki / 语言：覆盖 wiki 与 lang 参数即可
scrapy crawl fandom -a wiki=genshin-impact -a lang=en -a limit=10000
```

**参数**：
- `wiki`：Fandom 子站名（即 `<wiki>.fandom.com`）
- `lang`：`en` / `zh` 等
- `limit`：本次抓取的上限

### 5.2 抓取 Wikipedia

`wiki` spider 基于 `wikipedia-api` + Wikidata 类别枚举。

```bash
# 英文：Fictional_characters 类别下 1 万条
scrapy crawl wiki -a lang=en -a category=Fictional_characters -a limit=10000

# 中文：虚构角色
scrapy crawl wiki -a lang=zh -a category=虚构角色 -a limit=10000
```

**参数**：
- `lang`：维基百科语言代码
- `category`：起始类别名
- `limit`：上限

### 5.3 抓取 Reddit

`reddit` spider 通过 [arctic-shift](https://arctic-shift.photon-reddit.com/) 公开 API 拉取历史 submission，**无需 Reddit 账号或 API key**。

```bash
# 多 sub 同时抓，limit 是总条数
scrapy crawl reddit \
  -a subreddits=HPfanfiction,FanFiction,AO3,CharacterRant,fanfiction \
  -a limit=10000

# 限定时间窗
scrapy crawl reddit -a subreddits=onepiece -a after=2023-01-01 -a limit=5000
```

**参数**：
- `subreddits`：逗号分隔的子版列表
- `limit`：总条数上限
- `after`：（可选）起始日期 `YYYY-MM-DD`

### 5.4 抓取 AO3（限定 tag）

`ao3` spider 抓取指定 fandom tag 下的作品 summary + 元数据（不抓正文，规避版权）。

```bash
# Genshin Impact，500 页 ≈ 10000 条
scrapy crawl ao3 -a tag="Genshin Impact (Video Game)" -a max_pages=500

# 按点击量排序
scrapy crawl ao3 -a tag="Honkai: Star Rail" -a max_pages=200 -a sort=hits_count
```

**参数**：
- `tag`：AO3 fandom tag 全名
- `max_pages`：翻页上限（单 tag 最深 page=5000）
- `sort`：排序方式（如 `hits_count` / `kudos_count`）

### 5.5 抓取附件文档（PDF / DOCX）

爬虫在遇到文档类外链时会自动入队，由 Apache Tika（已通过 docker compose 启动）解析。无需单独命令。

---

## 6. 索引构建

抓取完成后，按顺序执行：

### 6.1 建 ES 索引

```bash
python -m indexer.build_index --source mongo --target es
# 96000+ 文档约 1–3 分钟
```

`--resume` 可断点续传。

### 6.2 离线 PageRank

```bash
python -m indexer.pagerank --write-back
# 基于 anchors 链接图，回写到 ES 的 pagerank 字段
```

### 6.3 语义向量化（可选但推荐）

```bash
# 先准备模型
export BGE_M3_MODEL_PATH=/path/to/bge-m3

# 全量
python -m indexer.embed

# 仅增量（如新加 AO3）
python -m indexer.embed --where source=ao3
```

无 GPU 时编码 10 万文档约 1–2 小时；若未安装模型，搜索时 α 路径自动降级，不影响其他功能。

### 6.4 健康检查

```bash
curl -s http://127.0.0.1:8000/health
# {"ok": true, "index": "isr_docs", "doc_count": 96109}
```

---

## 7. 启动后端

```bash
source .venv/bin/activate
uvicorn api.main:app --port 8000
```

接口文档（FastAPI 自带）：<http://127.0.0.1:8000/docs>

---

## 8. 启动前端

```bash
cd frontend
npm install            # 仅首次
npm run dev            # http://127.0.0.1:5173
```

构建产物预览：

```bash
npm run build && npx vite preview --port 5173
```

Vite 已在 `vite.config.ts` 配置把 `/api/*` 反代到 `http://127.0.0.1:8000`，无需额外 CORS 设置。

---

## 9. 前端使用指南

打开 <http://127.0.0.1:5173>，主要功能页：

### 9.1 注册 / 登录

顶栏 **登录 → 注册**，两步式：
1. 账号 + 密码
2. 冷启动偏好（喜欢的来源 source、tag 群）—— 后续搜索的 β·PersonalBoost 初值

匿名状态可直接使用搜索，但拿不到个性化加权。

### 9.2 搜索（`/search`）

- 搜索框输入关键词（示例：`Luffy` / `Zhongli` / `Harry Potter`），下方实时联想下拉
- **支持 4 种查询语法**：
  - 普通词：`luffy character`
  - 短语：`"impact on lore"`（带引号 → match_phrase）
  - 通配：`zhong*` / `hu?li`
  - 显式过滤：URL 参数 `?source=document` / `?rating=Mature` / `?language=English`
- **facet 边栏**：source（reddit/wiki/fandom/ao3/document） / rating / language 多选过滤

### 9.3 调节面板

展开"调节面板"：
- **α slider**（0 → 1）：左端权威（BM25 + PageRank 为主）/ 右端二创（语义相似度 × Obscurity 为主）
- **β slider**（0 → 5）：登录用户专用，越大个性化加权越强
- 调节立即生效，可对比同一关键词在不同 α/β 下的排序变化

### 9.4 结果卡片

每条结果含：
- 标题（高亮命中词） / source 徽标 / tag
- 摘要片段（`<em>` 高亮）
- **「详情」**：跳转 `/detail/{doc_id}`，看完整元数据
- **「快照」**：从本地 gzip 读取抓取时的原始 HTML
- 点击行为自动写入 `events` 集合 → 增量更新用户偏好

### 9.5 查询历史（`/log`）

登录后查看：
- 自己的历史查询（按时间倒序）
- 历史点击（含每次点击对应的 query 与 doc）

### 9.6 个人中心（`/me`）

- 修改默认 α / β
- 查看当前学习到的 `pref_sources` / `pref_tags`
- 重置偏好

---

## 10. 跑测试

```bash
source .venv/bin/activate
pytest tests/ -q --no-cov
```

覆盖 query_parser / ranking / suggest / 个性化更新 / auth / audit / `/doc/{id}` 路由（mock ES）等核心模块。

---

## 11. 跑评测

```bash
# 后端必须在跑（评测脚本走 HTTP API）
python eval/eval_alpha.py            # → reports/eval_alpha.md
python eval/eval_queries.py          # → reports/eval_queries.md
python eval/eval_personalization.py  # → reports/eval_personalization.md
```

三套脚本分别验证：α 滑块工作、6 种查询通路、β 个性化偏置生效。

---

## 12. 合规与风险红线

- 严格遵守 robots.txt；爬虫 User-Agent 含联系方式
- Fandom / Wiki 走官方 API，Reddit 走 arctic-shift 公开镜像，零代理成本
- 不爬取需要登录的私密内容、不绕过 CAPTCHA
- AO3 仅抓取作品 summary 与公开元数据，不抓正文
- 数据仅用于本课程作业，**不公开发布原始抓取数据**

---

## 13. License

课程作业，仅供学习交流。第三方依赖各自遵循其上游 License（ES / Tika / bge-m3 / Vue 等）。
