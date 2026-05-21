# 三源全量抓取指南（Runbook）

> 适用对象：fandom / wiki / reddit 三个 spider 的反复执行。
> 长生命周期文档，与 `docs/sec1-summary.md` `docs/sec2-summary.md` 互补。
> 这里不讲设计，只讲**怎么跑**和**怎么排错**。

---

## 0. 前置检查

每次跑爬虫前 30 秒做完这一节。

```bash
cd /mnt/d/wsl-share/ISR-scraper

# 1. 容器健康
# es / mongo / tika 应全部 healthy
docker compose up -d   # 如果上面看到 "Exited" 或没列出来

# 2. venv 激活
source .venv/bin/activate

# 3. 环境变量到位
test -f .env && echo "✓ .env exists" || cp .env.example .env

# 4. logs 目录
mkdir -p logs jobs

# 5. （仅 wiki 第一次需要）.env 里要有
#    WIKI_USERNAME, WIKI_BOT_PASSWORD
#    生成位置: https://en.wikipedia.org/wiki/Special:BotPasswords
```

---

## 1. 通用约定

### 1.1 强烈推荐：启用 JOBDIR 真断点续抓

每条 `scrapy crawl` 命令都加 `-s JOBDIR=../jobs/<spider>-<id>`。Ctrl+C 后用同一个
`JOBDIR` 再启动即可从断点接着抓。**不加 JOBDIR 等于"重跑靠 HTTPCACHE 兜底"，
万级以上不可靠**。

### 1.2 HTTPCACHE 管理

默认开启 3 天 TTL，存放在 `.scrapy/httpcache/`。

- **保留**：M2 阶段反复改代码、重跑 spider —— 不打外网更快
- **清除**：换 API 结构、换 wiki、换 category 时 —— `rm -rf .scrapy/httpcache`
- **关闭单次跑**：加 `-s HTTPCACHE_ENABLED=0` —— 适用于一次性正式跑

### 1.3 日志与监控

所有命令都用 `tee` 双写：

```bash
scrapy crawl <spider> [args] -L INFO 2>&1 | tee logs/<spider>-<run>.log
```

跑完看尾部 `Dumping Scrapy stats` 块，重点：

| stats 字段                                       | 期望值          |
|------------------------------------------------|--------------|
| `finish_reason`                                | `'closespider_itemcount'` 或 `'finished'` |
| `item_scraped_count`                           | ≥ `limit * 0.95` |
| `downloader/response_status_count/200`         | ≥ items × 1.0    |
| `downloader/response_status_count/429`         | **0**         |
| `downloader/response_status_count/5xx`         | < items × 0.01 |
| `retry/count`                                  | < items × 0.05 |

### 1.4 限速基线（**别动**，已在各 spider 内调好）

| Spider  | UA 来源        | robots          | 速率上限          |
|---------|----------------|-----------------|-----------------|
| fandom  | settings 全局  | OBEY            | 3 req/s（3 并发 + AutoThrottle） |
| wiki    | settings 全局  | **OFF**（API 豁免） | 2 req/s         |
| reddit  | settings 全局  | OFF             | 2 req/s         |

---

## 2. Fandom Spider

### 2.1 命令模板

```bash
# 改下面 1 行后整段执行
export WIKI_SLUG=harrypotter LIMIT=10000

cd crawler
scrapy crawl fandom -a wiki=$WIKI_SLUG -a limit=$LIMIT -s CLOSESPIDER_ITEMCOUNT=$LIMIT -s JOBDIR=../jobs/fandom-$WIKI_SLUG -L INFO 2>&1 | tee ../logs/fandom-$WIKI_SLUG.log
```

### 2.2 推荐 wiki 列表（与课程"小说同人创作"主题对齐）

| WIKI_SLUG          | 主题              | 主命名空间条目（估算） |
|--------------------|------------------|-----------------|
| `onepiece`         | 海贼王           | ~8000           |
| `genshin-impact`   | 原神             | ~12000          |
| `harrypotter`      | 哈利波特         | ~15000          |
| `hetalia`          | 黑塔利亚         | ~3000           |
| `naruto`           | 火影忍者         | ~20000          |
| `bleach`           | 死神             | ~6000           |
| `dragonball`       | 龙珠             | ~9000           |
| `attackontitan`    | 进击的巨人       | ~3000           |
| `mlp`              | 小马宝莉         | ~10000          |
| `demon-slayer`     | 鬼灭之刃         | ~2500           |

### 2.3 时长

3 req/s（3 并发）+ AutoThrottle 自适应：**1 万条 ≈ 55–75 分钟**。

### 2.4 可选参数

- `-a lang=en`（默认）/ `-a lang=zh` —— 中文 wiki（注意 `zh-hans / zh-hant` 子路径暂未支持）

### 2.5 实测案例

`onepiece` 抓到 **7859** 条后自然 `finished`（主命名空间穷尽）。这是数据源 ceiling，
不是 spider 问题；要单源破万就换 `genshin-impact` 或 `harrypotter`。

---

## 3. Wikipedia Spider

### 3.1 前置（一次性）

1. 登录 [https://en.wikipedia.org/wiki/Special:BotPasswords](https://en.wikipedia.org/wiki/Special:BotPasswords)
2. 新建 bot：**name 任意**，**Grants 只勾 "Basic rights"**
3. `.env` 写入：
   ```env
   WIKI_USERNAME=YourAccount@BotName
   WIKI_BOT_PASSWORD=生成的一次性长串
   ```

### 3.2 命令模板

```bash
# 改下面 1 行后整段执行（首次须先在 .env 配 WIKI_USERNAME / WIKI_BOT_PASSWORD）
export CATEGORY=Fictional_characters LIMIT=10000 MAX_DEPTH=4

scrapy crawl wiki -a lang=en -a category=$CATEGORY -a limit=$LIMIT -a max_depth=$MAX_DEPTH -s CLOSESPIDER_ITEMCOUNT=$LIMIT -s JOBDIR=../jobs/wiki-$CATEGORY -L INFO 2>&1 | tee ../logs/wiki-$CATEGORY.log
```

启动后应看到：

```
[wiki] using bot login as LumineNoble@ISR-hw4-scraper
[wiki] login OK as LumineNoble
```

### 3.3 推荐 category 列表

| CATEGORY                              | 容量      | 推荐 `max_depth` |
|---------------------------------------|---------|-----------------|
| `Fictional_characters`                | ~10000+ | 4               |
| `Fictional_characters_by_medium`      | ~50000+ | 3               |
| `Fictional_characters_by_creator`     | ~30000+ | 3               |
| `Characters_in_American_novels`       | ~5000   | 4               |
| `Characters_in_British_novels`        | ~5000   | 4               |
| `Anime_and_manga_characters`          | ~8000   | 3               |
| `Video_game_characters`               | ~15000  | 3               |

### 3.4 时长

固定 2 req/s × ~10000 请求 ≈ **85 分钟 / 万条**。

### 3.5 已知坑

- 消歧页 `_(disambiguation)` 暂不过滤 —— 会进库；M3+ 阶段加正则
- `max_depth` 调大会拉到边缘类目（如"以姓氏 Smith 命名的角色"），不一定垂直
- API 偶发 `Got data loss` warning —— **不要**关 `DOWNLOAD_FAIL_ON_DATALOSS`，让 retry 兜底

---

## 4. Reddit Spider（via arctic-shift）

### 4.1 前置

**零凭据需求**。arctic-shift 是 Pushshift 后续社区镜像，公开免登录。但请求必须带
我们 settings.py 中已配的 UA，否则会被 403。

### 4.2 命令模板

```bash
# 改下面 2 行后整段执行；EXTRA 可空或填 "-a after=2024-01-01" 等
export SUBREDDITS=FanFiction,AO3,HPfanfiction LIMIT=10000 RUN_ID=reddit-fanfic
export EXTRA=""

scrapy crawl reddit -a subreddits=$SUBREDDITS -a limit=$LIMIT $EXTRA -s CLOSESPIDER_ITEMCOUNT=$LIMIT -s JOBDIR=../jobs/$RUN_ID -L INFO 2>&1 | tee ../logs/$RUN_ID.log
```

### 4.3 推荐 subreddit 列表

| 主题维度        | 建议 subreddits（逗号拼）                                                |
|---------------|---------------------------------------------------------------------|
| 同人通用       | `FanFiction,fanfiction,AO3,HPfanfiction`                                 |
| 角色讨论       | `CharacterRant,whowouldwin,fixedfandoms`                                |
| 单 IP 深度（按你的兴趣换） | `onepiece,genshin_impact,HazbinHotel,HelluvaBoss,HogwartsLegacy,DBZ,Naruto` |
| 跨界 / 元讨论 | `crossover,worldbuilding,writing`                                       |

一次跑 5–10 个 sub，limit 全局分摊（spider 内部 `_yielded` 跨 sub 累计），
**先到先得**，所以排在前面的 sub 会拿走更多份额。需要均匀分布就**多次单 sub 跑**。

### 4.4 时间窗参数

- `before`、`after` 接受 ISO 日期（`2023-01-01`）或 unix 秒（`1672531200`）
- 不传 = 全历史
- 大型 sub（如 `FanFiction`）历史可上百万条，记得加 `limit` 兜底

### 4.5 时长

API 限速 ~2 req/s × 每页 100 条 ≈ **50 条/秒 = 1 万条/3 分钟**。比 fandom/wiki 快得多。

### 4.6 常用命令样例

```bash
# 同人通用 sub，最近 1 年，1 万条
scrapy crawl reddit -a subreddits=FanFiction,fanfiction,AO3,HPfanfiction -a after=2024-01-01 -a limit=10000 -s CLOSESPIDER_ITEMCOUNT=10000 -s JOBDIR=../jobs/reddit-fanfic-2024 -L INFO 2>&1 | tee ../logs/reddit-fanfic-2024.log

# 单 IP 深挖（原神历史 5 万）
scrapy crawl reddit -a subreddits=genshin_impact -a limit=50000 -s CLOSESPIDER_ITEMCOUNT=50000 -s JOBDIR=../jobs/reddit-genshin -L INFO 2>&1 | tee ../logs/reddit-genshin.log
```

---

## 5. 累计 10 万条的源组合策略

`design.md` 总目标 ≥ 10 万。一份可行的分配：

| 源       | 建议来源                                                    | 单源条数  | 累计   |
|--------|---------------------------------------------------------|--------|------|
| fandom | onepiece + harrypotter + naruto + mlp + genshin-impact  | 40000  | 40k  |
| wiki   | Fictional_characters + Video_game_characters            | 25000  | 65k  |
| reddit | FanFiction + AO3 + HPfanfiction + 单 IP 多个               | 35000  | 100k |

每条建议都对应章节 2–4 的命令模板，把 `<...>` 替换进去即可。

跑完一批要先验证（章节 6）再跑下一批，否则错误堆积难定位。

---

## 6. 验证脚本

每跑一批后执行；产出报告应该全 0 或符合预期。

```bash
source .venv/bin/activate && python - <<'PY'
"""三源累计验证：计数、脏数据、快照对齐、tag 分布。"""
import os, pathlib, pymongo
from collections import Counter
from dotenv import load_dotenv

load_dotenv(".env")
uri = (f"mongodb://{os.getenv('MONGO_USER','isr')}:{os.getenv('MONGO_PASSWORD','isr_dev_pw')}"
       f"@localhost:{os.getenv('MONGO_PORT','27017')}/?authSource=admin")
db = pymongo.MongoClient(uri)[os.getenv("MONGO_DB", "isr")]
col = db["raw_pages"]

print("=== 计数 ===")
print(f"  total                       {col.count_documents({})}")
for s in ("fandom", "wiki", "reddit"):
    print(f"  source={s:<10}        {col.count_documents({'source': s})}")

print("\n=== 脏数据（全应为 0） ===")
print(f"  URL 含 HTML 残片              {col.count_documents({'url': {'$regex': '<'}})}")
print(f"  title 缺失或空                {col.count_documents({'$or': [{'title': None}, {'title': ''}]})}")
print(f"  doc_id 缺失                  {col.count_documents({'doc_id': {'$exists': False}})}")
print(f"  snapshot_path 缺失            {col.count_documents({'snapshot_path': {'$exists': False}})}")

print("\n=== Tag 分布 ===")
for x in col.aggregate([{"$group": {"_id": {"source": "$source", "tag": "$tag"}, "n": {"$sum": 1}}}]):
    print(f"  {x['_id']['source']:<10} {x['_id']['tag']:<10} {x['n']}")

print("\n=== 快照对齐 ===")
snap = pathlib.Path("data/snapshots")
files = list(snap.rglob("*.html.gz"))
total = sum(f.stat().st_size for f in files)
print(f"  快照文件数                   {len(files)}")
print(f"  Mongo 总数                  {col.count_documents({})}")
print(f"  差值（>0 说明 pipeline 故障） {col.count_documents({}) - len(files)}")
print(f"  快照总大小                   {total / 1024 / 1024:.1f} MB")
PY
```

---

## 7. 故障排查

| 现象                                                   | 根因                                      | 处理                                                          |
|-----------------------------------------------------|-----------------------------------------|-----------------------------------------------------------|
| `ServerSelectionTimeoutError` 连 mongo               | Docker 容器没起                            | `docker compose up -d`                                       |
| `command not found: docker`                         | Docker Desktop WSL 集成被禁                  | Docker Desktop → Settings → Resources → WSL Integration → 重启 |
| `command not found: scrapy`                         | venv 没激活                                | `source .venv/bin/activate`                                   |
| `scrapy: error: running ... more than one spider`   | 命令多行复制时反斜杠续行被吃                       | 改单行整段复制                                                 |
| Wiki spider `Got data loss`                         | Wikipedia 偶发截断 chunked                  | 不用动，retry 自动兜底；**别**关 `DOWNLOAD_FAIL_ON_DATALOSS` |
| Wiki spider `login FAILED`                          | Bot Password 错 / 过期                     | `Special:BotPasswords` 重生成                                 |
| Reddit 全部 403                                       | UA 没设 / arctic-shift 临时挂                | 确认 settings.py UA 已含联系邮箱；试 `curl -A "$UA" <api_url>` |
| Reddit `data` 为空                                    | subreddit 拼错（区分大小写不严格但 sub 名要对） | 在 reddit.com 验证 sub 存在                                    |
| Ctrl+C 后重启从 0 开始                                  | 没启用 JOBDIR                              | 加 `-s JOBDIR=../jobs/<name>`，下次有效                          |
| 长跑磁盘吃紧                                            | `.scrapy/httpcache/` 涨到 GB              | `rm -rf .scrapy/httpcache`（不影响已抓数据）                      |
| Mongo 越写越慢                                          | doc_id 唯一索引大量冲突                        | 正常现象（upsert）；如不需要保留旧批，清库再跑                      |
| spider 跑到 `_yielded == limit` 但 Mongo 没那么多        | pipeline DropItem（脏 URL）                | 调高 limit 10% 兜底；或查 logs/<spider>*.log 找 DropItem 记录 |

---

## 8. 一次性清库（慎用）

```bash
# 清 Mongo 某源
docker exec isr-mongo mongosh -u isr -p isr_dev_pw --authenticationDatabase admin --quiet \
  --eval 'db.getSiblingDB("isr").raw_pages.deleteMany({source:"reddit"})'

# 清对应快照（不区分源；如果想保留其他源，先备份）
# 注意先 ls 确认目录范围再 rm
find data/snapshots -name "*.html.gz" -delete
find data/snapshots -mindepth 1 -type d -empty -delete

# 清 HTTPCACHE
rm -rf .scrapy/httpcache

# 清 JOBDIR（重新计数）
rm -rf jobs/<name>
```
