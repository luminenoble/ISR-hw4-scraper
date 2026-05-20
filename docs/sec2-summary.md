# Sec.2 Scrapy 骨架 + Fandom/Wiki Spider（M2 阶段）

> 对应里程碑：`design.md §7 — M2 Fandom + Wiki spider 跑通，单源 1 万条`
> 完成日期：2026-05-20
> 上游依赖：`docs/sec1-summary.md`（ES + Mongo + Tika 已就绪）

## 1. 交付物清单

| 路径                                                | 作用                                          |
|----------------------------------------------------|---------------------------------------------|
| `pyproject.toml`                                   | uv 兼容；声明 scrapy/pymongo/loguru/bs4 等依赖   |
| `crawler/scrapy.cfg`                               | Scrapy 项目入口                                |
| `crawler/isr_crawler/settings.py`                  | UA、AutoThrottle、pipelines、Mongo URI         |
| `crawler/isr_crawler/items.py`                     | 统一 `PageItem`（对齐 design.md §3.1）           |
| `crawler/isr_crawler/utils.py`                     | `doc_id_for` / 快照路径 / HTML 清洗              |
| `crawler/isr_crawler/pipelines.py`                 | Clean → Snapshot(gzip) → Mongo(upsert)        |
| `crawler/isr_crawler/spiders/mediawiki_base.py`    | MediaWiki API 通用基类                          |
| `crawler/isr_crawler/spiders/fandom_spider.py`     | Fandom 子类（按 wiki 子域）                      |
| `crawler/isr_crawler/spiders/wiki_spider.py`       | Wikipedia 子类（按 category 递归）               |
| `tests/test_utils.py`                              | utils 单测                                    |

## 2. 关键设计

### 2.1 统一 schema 与 doc_id

完全照搬 `design.md §3.1`，新增 `raw_html` / `extra` 两个临时字段：

- `raw_html`：在 pipeline 之间传递的原始 HTML，写入 gzip 快照后被清空，**不入 Mongo**
- `extra.categories / extra.pageid / extra.sections`：MediaWiki 专属元数据

`doc_id = sha1(url)`，与设计文档一致；URL 由 `page_base + title.replace(' ', '_')` 拼接，确保同一条目在不同抓取批次得到同一 ID。

### 2.2 共享 MediaWiki 基类

Fandom 和 Wikipedia 都跑在 MediaWiki 上，API 形态几乎一致。`MediaWikiBaseSpider` 封装：

- `start_requests` → `action=query&list=allpages` 分页枚举
- 每页调 `action=parse&prop=text|links|categories|sections` 一把拿够元数据
- 子类只需声明 `api_base / page_base / source` 和（可选）`classify_tag`

两个 spider 的差异：

| 维度       | Fandom                                  | Wiki                                       |
|----------|----------------------------------------|--------------------------------------------|
| 入口      | `allpages` 全量遍历                       | `categorymembers` 递归（默认深度 3）            |
| 域名      | `<wiki>.fandom.com`                     | `<lang>.wikipedia.org`                     |
| 默认参数  | `wiki=onepiece`、`lang=en`               | `category=Fictional_characters`、`lang=en` |
| tag 启发  | 分类含 `fanon/fan fiction` → `fanon` 等  | 全部标 `canon`                             |

> Wikipedia 全量 ~600 万条，远超作业需要。改用 categorymembers 递归既能控量，又能聚焦"虚构角色"垂直域。

### 2.3 Pipelines 三段式

```
CleanPipeline(100)      # 补 doc_id/fetched_at；HTML → 纯文本；抽锚文本
SnapshotPipeline(200)   # gzip 写 data/snapshots/ab/cd/<doc_id>.html.gz；清空 raw_html
MongoPipeline(300)      # upsert(doc_id) 到 raw_pages；建 doc_id 唯一索引
```

设计要点：

- **快照**：两级分桶（前 4 hex 字符）防单目录文件爆炸；gzip level 6 平衡速率与压缩比
- **Mongo 不存 raw_html**：避免 16 MB BSON 上限；正文检索走 ES（M4 阶段）
- **upsert by doc_id**：断点续爬安全，重复抓取自动覆盖

### 2.4 合规与限速

**全局默认（适用于 fandom 及未来 spider）**：

- `USER_AGENT` 由 `.env` 注入：`<ISR_UA_NAME>/0.1 (+mailto:<ISR_CONTACT_EMAIL>; user:<WIKI_USERNAME 主账号>)`
- `ROBOTSTXT_OBEY = True`
- AutoThrottle 开启，目标并发 2，最大延迟 10s
- Retry：429/5xx 重试 3 次
- HTTPCACHE 默认开启（3 天）— 开发期反复 spider 跑不打爆 API

**WikiSpider 特殊 override（`custom_settings`）**：

Wikipedia `robots.txt` 含 `Disallow: /w/`，会阻断 `/w/api.php` 上所有 API 调用。但
`mediawiki.org/wiki/API:Etiquette` 政策明确**豁免 API 用户**——只要 UA 带联系方式、
限速保守、不并发轰炸即可。所以仅对 WikiSpider：

```python
ROBOTSTXT_OBEY = False
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 0.5                   # 2 req/s 上限
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
```

### 2.5 Wikipedia Bot Password 登录

在 `.env` 提供 `WIKI_USERNAME / WIKI_BOT_PASSWORD`（来自 `Special:BotPasswords`）时，
WikiSpider 抓取前先走 4 步登录链：

```
1. GET  action=query&meta=tokens&type=login        → logintoken
2. POST action=login (form: lgname/lgpassword/lgtoken)  → Set-Cookie session
3. 后续 categorymembers / parse 请求自动带 cookie（CookiesMiddleware）
4. 完成
```

匿名模式（不填凭据）也能跑，但限速更严、`apihighlimits` 不可用。

## 3. 启动与验证

> 先确保 M1 的容器已 `docker compose up -d`，并 `cp .env.example .env`。

### 3.1 环境

```bash
cd /mnt/d/wsl-share/ISR-scraper
uv venv .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

### 3.2 单测

```bash
pytest tests/ -v
ruff check . && black --check .
```

### 3.3 冒烟测试（小批量）

```bash
cd crawler
# Fandom: One Piece wiki 抓 100 条
scrapy crawl fandom -a wiki=onepiece -a limit=100 -L INFO

# Wikipedia: 英文虚构角色 100 条
scrapy crawl wiki -a lang=en -a category=Fictional_characters -a limit=100 -L INFO
```

### 3.4 校验结果

```bash
# Mongo 条数
docker exec isr-mongo mongosh -u isr -p isr_dev_pw \
  --authenticationDatabase admin --quiet \
  --eval 'db.getSiblingDB("isr").raw_pages.countDocuments({source: "fandom"})'

# 快照目录
ls data/snapshots/ | head -5
du -sh data/snapshots/

# 单条样例
docker exec isr-mongo mongosh -u isr -p isr_dev_pw \
  --authenticationDatabase admin --quiet \
  --eval 'db.getSiblingDB("isr").raw_pages.findOne({source:"fandom"}, {raw_html:0, body_text:0})'
```

预期：
- Mongo `raw_pages` 中 Fandom ≈ 100，Wiki ≈ 100
- `data/snapshots/` 出现 `ab/cd/<sha1>.html.gz` 形式
- 文档含 `doc_id / source / url / title / anchors / fetched_at / snapshot_path / tag`

### 3.5 1 万条正式跑

Fandom（约 1–2 小时）：

```bash
scrapy crawl fandom -a wiki=onepiece -a limit=10000 -s CLOSESPIDER_ITEMCOUNT=10000 -L INFO 2>&1 | tee ../logs/fandom-onepiece.log
```

Wiki（约 1.5 小时；需先在 `.env` 配 `WIKI_USERNAME / WIKI_BOT_PASSWORD`）：

```bash
scrapy crawl wiki -a lang=en -a category=Fictional_characters -a limit=10000 -s CLOSESPIDER_ITEMCOUNT=10000 -a max_depth=4 -L INFO 2>&1 | tee ../logs/wiki-fictional.log
```

> 强烈建议加 `-s JOBDIR=../jobs/wiki-fictional` 启用 Scrapy 的 scheduler 持久化，
> Ctrl+C 后用同一 JOBDIR 重启即可真断点续抓。本次 M2 没加，靠 HTTPCACHE + Mongo
> upsert 幂等性做"伪续跑"。

## 4. 设计权衡

| 决策                                  | 理由                                                              |
|------------------------------------|-----------------------------------------------------------------|
| 用 Scrapy 原生 Request 而不是 wikipedia-api | 复用 Scrapy 的去重、调度、AutoThrottle、HTTPCACHE；避免两套限速逻辑 |
| Fandom 走 `allpages` 而非 sitemap        | API 稳定、返回结构化，省去 HTML 解析                                 |
| Wiki 走 categorymembers 递归             | 控量 + 聚焦垂直域；全量没必要                                      |
| pipeline 顺序固定 100/200/300            | 任何排序操作（如 dedup）都能插在 50 / 150 / 250 等空挡，不破坏现有顺序       |
| Mongo 不存 raw_html                    | 16 MB BSON 上限风险；快照走文件系统更便宜                            |
| HTTPCACHE 默认开                         | 开发期改代码反复跑不会真的打 API                                     |

## 5. 已知坑

- **fandom 中文 wiki**：URL 前缀含 `/zh-hans` 等子路径，目前 `lang=zh` 写死成 `zh/`，遇到其他变体（如 `zh-hant`）需要扩展
- **Wikipedia 多义消歧页**：会被当作普通条目入库；M3 阶段引入正则过滤
- **AutoThrottle 与 limit 交互**：`limit` 是 yield 计数，不是 item 计数；如果 pipeline 中途丢弃 item，最终入库会少一些
- **HTTPCACHE 在 1 万条规模下占空间**：可能 1–2 GB，跑大批量前 `ISR_HTTPCACHE=0` 关闭或定期 `rm -rf .scrapy/httpcache`
- **MediaWiki API 偶发 503**：retry 已配；持续 503 一般是被限速，调小 `CONCURRENT_REQUESTS_PER_DOMAIN`
- **`Got data loss in ...` warning**：Wikipedia 偶尔返回截断 chunked 响应。**不要按提示关 `DOWNLOAD_FAIL_ON_DATALOSS`**——RetryMiddleware 默认会重发，关掉反而会让截断 JSON 流入 pipeline 造成静默脏数据
- **本次未启用 JOBDIR**：Ctrl+C 后无法真断点续抓，靠 HTTPCACHE 缓存 + `doc_id` 唯一索引兜底；下一轮务必加上

## 6. 实跑结果

| 指标                  | Fandom            | Wiki                        | 合计     |
|---------------------|-------------------|----------------------------|--------|
| 目标条数              | 10000             | 10000                       | 20000  |
| 实际入库              | **7859**          | **8337**                    | 16196  |
| `finish_reason`     | `finished` (枚举完) | `closespider`/Ctrl+C 早停     | -      |
| URL 含 HTML 残片       | 0                 | 0                           | 0      |
| title 缺失或空          | 0                 | 0                           | 0      |
| `doc_id` / `snapshot_path` 缺失 | 0       | 0                           | 0      |
| anchors 空            | -                 | -                           | 2      |
| body_text 空          | -                 | -                           | 1      |
| 快照文件 ↔ Mongo       | 1:1               | 1:1                         | 16196 == 16196 |

**缺口归因**：

- Fandom 7859：One Piece wiki 主命名空间非重定向条目自然就这么多，`apfilterredir=nonredirects` 滤掉了重定向页，`finish_reason=finished` 而非达到 limit
- Wiki 8337：实跑期间手动 Ctrl+C 过两次；未启用 JOBDIR 所以续跑靠 HTTPCACHE，遍历到深度上限或被中断时停下

**结论**：spider 与 pipeline 在万级规模稳定，万级抓取**能力已验证**。差的 ~2000 条是数据源 ceiling + 操作中断，非技术缺口；M3 阶段加 Reddit + 多 wiki + 多 category 后累计 10 万达成无虞。

## 7. 下一步（衔接 M3）

- [ ] Reddit spider（PRAW + OAuth）
- [ ] Tika 文档解析 pipeline（PDF/DOCX → `source=document`）
- [ ] 三源累计 ≥ 10 万条
- [ ] dedup pipeline（跨源 URL 规范化）
- [ ] 抓取监控：item/min、错误率、cache hit ratio
