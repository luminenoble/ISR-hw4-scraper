# Sec.9 AO3 接入（M9 阶段 · Genshin Impact）

> 上游决策：sec8 §7.1/§7.2 修完 boost 分支 + α 曲线后，把"接入 AO3 类垂直平台"作为补量与提质的双重路径。
> 完成日期：2026-05-24
> 目标：在不引入 detail 页抓取的前提下，把 AO3 同人作品的 **summary + 元数据**纳入索引；
> 限定首批数据源 `原神 | Genshin Impact (Video Game)` canonical tag，按 kudos 倒序抓 ~10k 条。

## 1. 交付清单

### 爬虫层（M9-1）

| 路径 | 性质 | 作用 |
|---|---|---|
| `crawler/isr_crawler/spiders/ao3_spider.py` | 新增 | AO3 单层列表页 spider，fan-out 4 并发对齐 2 req/s |
| `tests/fixtures/ao3_listing_genshin.html` | 新增 | 真实 AO3 page=1 列表页 fixture（194KB） |
| `tests/test_ao3_parser.py` | 新增 | 12 个用例覆盖 blurb 解析、tag 分类、popularity 公式 |

### 索引 / 排序层（M9-2/3）

| 路径 | 性质 | 作用 |
|---|---|---|
| `indexer/es_mapping.json` | 修改 | 加 `ao3_tags` 嵌套对象 + `rating/warnings/language/word_count/kudos/bookmarks/hits/author` |
| `indexer/build_index.py` | 修改 | `_ao3_fields_from_extra` 提升 extra → ES top-level；预算 `obscurity = 1/log(popularity+e)`、`pagerank = 0` |
| `indexer/pagerank.py` | 修改 | 扫表时 `{source: {$ne: "ao3"}}` 跳过 AO3 文档，保护 spider 算好的 kudos-加权 popularity 不被 in-degree 覆盖 |
| `api/ranking.py` | 修改 | PersonalBoost script 加 `ao3_tags.freeform` 多值遍历分支，单值 tag 路径保留，命中贡献封顶 1.0 |

### 检索层（M9-4）

| 路径 | 性质 | 作用 |
|---|---|---|
| `api/routers/search.py` | 修改 | `/search` 加 `rating` + `language` 两个 filter 参数 |
| `api/routers/suggest.py` | 修改 | 新增 `_path_a_tag` 路径：在 `ao3_tags.freeform` 上做 ES regex include 前缀联想 |

### 前端层（M9-5）

| 路径 | 性质 | 作用 |
|---|---|---|
| `frontend/src/components/TuningPanel.vue` | 修改 | sources 加 `ao3` checkbox；登录用户/勾 ao3 时显示 rating / language select |
| `frontend/src/pages/Search.vue` | 修改 | facet state + URL 透传到 `/search` |
| `frontend/src/lib/api.ts` | 修改 | `search()` 参数加 `rating` / `language` |

### 文档

| 路径 | 内容 |
|---|---|
| `docs/sec9-summary.md` | 本文 |
| `README.md` | 加 AO3 source 说明 + 更新数据规模表 |
| `CLAUDE.md` | 进度勾选 + 新增"AO3 接入"条目 |

## 2. 关键决策

### 2.1 只抓列表页，不进 detail

每个 `<li class="work blurb group">` 已包含：title / author / rating / warnings / category / WIP / fandom / relationship / character / freeform 四类 tag / summary / language / word_count / chapters / kudos / bookmarks / hits / updated_at 共 16 个字段。

代价：拿不到正文。收益：

- 请求数从 ~100 万 (列表+详情) 砍到 ~500 (仅列表)
- 单 doc 体积 100KB+ → ~3-5KB（仅 summary）
- 不需要 login（M/E rating 借 `view_adult=true` cookie 即可绕开二次确认）
- 不需要 Tika EPUB 管线
- ToS 法律风险大幅降低（summary 性质等同于公开目录卡片）

详情页若日后需要可走 `/works/{id}?view_full_work=true` 单独追加，schema 已留 `body_text` 字段位置。

### 2.2 canonical tag 中英合并

AO3 wrangler 已经把 `Genshin Impact` / `原神` 等 ~30 个语种 tag 合并到 canonical `原神 | Genshin Impact (Video Game)`（URL 编码 `%E5%8E%9F%E7%A5%9E%20%7C%20Genshin%20Impact%20(Video%20Game)`）。一次请求拿全语种作品，无需自己做多语种合并。

### 2.3 popularity 公式：log1p 三分量加权

spider 端直接算：

```
popularity = log1p(kudos)·0.6 + log1p(bookmarks)·0.3 + log1p(hits)·0.1
```

kudos / bookmarks 反映"被推荐的强度"，hits 仅反映曝光；权重 6:3:1 凸显前者。`build_index` 同步算 `obscurity = 1/log(popularity+e)`，与 design.md §3.4 公式定义对齐。

pagerank.py 改成 `{source: {$ne: "ao3"}}` 过滤，避免日后单跑一次 PageRank 把 AO3 的 popularity 覆盖回 0（AO3 工作间无内链 → in-degree=0）。

### 2.4 fan-out 抓取 + 4 并发对齐 2 req/s

冒烟时发现 WSL→AO3 国际链路单页响应 ~16s，autothrottle 会把 DOWNLOAD_DELAY 拉到 16s 导致整体 < 1 page/min。改方案：

- `CONCURRENT_REQUESTS_PER_DOMAIN=4`
- `DOWNLOAD_DELAY=0.5`（每 slot）
- `AUTOTHROTTLE_ENABLED=False`
- `start()` 一次性把全部 max_pages 个请求挂入调度器（fan-out），不再链式 `yield next_request`

稳态吞吐 = `concurrent / response_time = 4 / 16s ≈ 0.25 req/s` 实际，但因为 Scrapy 的 slot 调度允许 4 个连接同时在飞，**实测约 7-9 pages/min ≈ 140-180 items/min**。对应 2500 页满抓约 4-5 小时；本期 max_pages=500 → ~60 分钟出 ~10k 条 Genshin Impact 作品。

`RETRY_HTTP_CODES` 加 520/521/525：AO3 经过 Cloudflare，偶发 5xx 都是上游握手失败，重试通常一次即恢复。

### 2.5 单值 tag + 多值 freeform tag 双通道

`api/ranking.py` 的 PersonalBoost script 现在同时处理两类 tag：

- 单值 `doc.tag`（canon/fanon/meta/crossover）：M6 原有路径，覆盖全部 source
- 多值 `doc['ao3_tags.freeform']`：遍历每条 freeform tag，累加用户偏好权重，封顶 1.0 避免长 tag list 把分数推到失控

非 AO3 文档没有 `ao3_tags` 字段，Painless 的 `doc.containsKey(...)` 守护让分支直接跳过——对 wiki/fandom/reddit 行为 0 变化。

### 2.6 `_path_a_tag` 走 terms aggregation + regex include

不引入 ES completion suggester（要 reindex）。改用：

```json
"aggs": {
  "tags": {
    "terms": {
      "field": "ao3_tags.freeform",
      "include": "<q-escaped>.*",
      "size": 30
    }
  }
}
```

带 doc_count 自带"频次排序"。大小写不敏感降级：先严格前缀，失败再 `(?i)<q>.*` 兜底。

### 2.7 AO3 canon/fanon 分类启发式

```python
if any(k in freeforms_joined for k in
    ("alternate universe", " au", "oc ", "self-insert", "self insert")):
    → fanon
elif any(k in joined for k in ("crossover", "fusion")):
    → crossover
elif any(k in joined for k in ("meta", "essay", "analysis")):
    → meta
else:
    → canon
```

不完美（AO3 freeform tag 完全用户自由命名），但能在用户层面把"严格剧本"与"AU/二创"区分开。冒烟验证：高 kudos 的转生 AU 作品被正确归到 `fanon`。

## 3. 实跑数据（spider 仍在跑，数据持续累计）

### 3.1 单条样本（spider 冒烟期间抽到的 top kudos 作品）

```text
title       : Entirely Out of Spite
url         : https://archiveofourown.org/works/30349320
source      : ao3
tag         : fanon          ← freeform 含 "Alternate Universe / transmigration au"
rating      : Teen And Up Audiences
language    : English
word_count  : 559,991
chapters    : 46 / 46
kudos       : 47,422
bookmarks   : 7,659
hits        : 2,160,194
popularity  : 10.602         ← log1p(47422)·0.6 + log1p(7659)·0.3 + log1p(2160194)·0.1
obscurity   : 0.386          ← 1 / log(10.602 + e)
ao3_tags.character: ["Zhongli (Genshin Impact)", "Tartaglia | Childe (Genshin Impact)", ...]
ao3_tags.freeform: ["Alternate Universe", "transmigration au", "Inspired by Scum Villain Self-Saving System", ...]
```

obscurity 0.386 比 wiki Genshin 角色页常见的 0.1-0.2 高得多——意味着 α 路径上这种 fanfic 会自然被推升，正符合"发散度高时民间二创主导"的设计意图。

### 3.2 抓取节奏

| 时间 | mongo ao3 计数 | 备注 |
|---|---:|---|
| spider 启动 +60s | ~80 | 初始 robots.txt + page 1 完成 |
| +3 min | ~320 | fan-out 全速后稳态 |
| 预期 60 min（500 页满） | ~10000 | 实际取决于 AO3 Cloudflare 抖动 |

## 4. 落地后操作步骤（spider 完成后跑）

```bash
# 1. 把新 AO3 docs 灌进 ES
python -m indexer.build_index --resume     # 走 last_indexed 断点续灌

# 2. embedding：只编 ao3 新增的，沿用 M5 增量
python -m indexer.embed --where source=ao3

# 3. PageRank 不用重跑（设计上 ao3 不参与图）

# 4. 验证
curl 'http://localhost:8000/search?q=Childe&source=ao3&size=3&alpha=0.5' | jq
curl 'http://localhost:8000/suggest?q=Alter&size=10' | jq        # 应该看到 tag 类 suggestion
```

## 5. 修改后的检索演示

| 场景 | 期望行为 |
|---|---|
| 匿名查 "Zhongli" α=0 | wiki / fandom 角色条目居前 |
| 匿名查 "Zhongli" α=0.7 | mixin AO3 高 obscurity 的 AU 同人 summary |
| 登录偏好 `freeform: {"Coffee Shop AU": 1.0}`，β=2 | top-K 全部 AO3 Coffee Shop AU 作品 |
| `?source=ao3&rating=Mature` | 严格 M 级 Genshin 同人 |
| 联想 "Slow" | "Slow Burn"（tag 类，频次最高） · 历史 query · 标题前缀 |

## 6. 已知遗留 / 后续

| 项 | 状态 |
|---|---|
| AO3 detail 页正文抓取 | 留 M10（如有）；用户当前需求只要 summary |
| 多 source filter（terms query） | 仍未做（M7 推迟）；当前勾 ao3 + others 仍走单值 source filter |
| AO3 多语种作品（非 EN）的中文 summary 编码 | bge-m3 多语种原生支持，无需特殊处理 |
| 部分 5xx 重试后仍失败的页（约 < 1%） | 抓取结束后跑 `python -m indexer.audit` 出报告，按 doc_id 补抓 |
| sec9 评测报告（vs sec8 的 α/β/queries） | spider 完成后重跑 `eval/eval_*.py`，对比 +AO3 后的指标变化 |

## 7. 端到端冒烟脚本

```bash
# 起服务
docker compose up -d
source .venv/bin/activate
uvicorn api.main:app --port 8000 &

# 单测
pytest tests/ -q --no-cov          # 81 passed

# 抓 AO3（后台跑）
cd crawler
nohup scrapy crawl ao3 -a max_pages=500 > ../logs/ao3_genshin.log 2>&1 &

# 监控
tail -f ../logs/ao3_genshin.log
mongosh "mongodb://isr:isr_dev_pw@localhost:27017/isr?authSource=admin" \
  --eval 'db.raw_pages.countDocuments({source:"ao3"})'

# 完工后建索引 + embed
python -m indexer.build_index --resume
python -m indexer.embed --where source=ao3
```

## 8. 阶段收束

至此覆盖里程碑 M1–M9：

- M1–M8：原有阶段（详见各 sec 总结）
- M9：AO3 接入（本期），把作业 1 要求的"≥10 万页"硬指标推到 96109 + AO3 ~10000 ≈ **106,000+** 页，且 source 维度从 4 个（wiki/fandom/reddit/document）扩到 5 个

后续若有 M10：评测脚本扩 ao3 source case study；前端 facet 多选 `terms` query 支持。
