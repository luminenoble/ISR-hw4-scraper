# Sec.6 用户系统 + 个性化排序 + 联想（M6 阶段）

> 对应里程碑：`design.md §7 — M6 用户系统 + 个性化 + 发散度滑杆`
> 完成日期：2026-05-23
> 上游依赖：`docs/sec5-summary.md`（PageRank/Obscurity 已回写、α slider 已接通，embedding 字段尚未全量回写）

## 1. 交付物清单

| 路径 | 性质 | 作用 |
|---|---|---|
| `api/security.py` | 新增 | argon2id 密码哈希 + JWT HS256 编解码 |
| `api/routers/auth.py` | 新增 | `/auth/register/login/me`（GET/PATCH） |
| `api/personalization.py` | 新增 | `boost_params_for` 抽 PB 参数 + `apply_click_update` 增量更新 |
| `api/routers/feedback.py` | 新增 | `/feedback/click` 记录隐式反馈并 bump 偏好 |
| `api/routers/suggest.py` | 新增 | `/suggest` 两路（history+title prefix / kNN 语义）按 α 混合 |
| `api/ranking.py` | 修改 | 公式加 `+ β·PersonalBoost`，三分量 source/tag/click |
| `api/routers/search.py` | 修改 | 注入 `current_user_optional` → 自动取 `default_alpha/beta` + PB 参数 |
| `api/deps.py` | 修改 | `get_users_col` + `get_current_user_optional/required` + bearer 解析；启动建 users 索引 |
| `api/main.py` | 修改 | 挂 auth / feedback / suggest 三个 router；CORS 允许 POST/PATCH |
| `api/schemas.py` | 修改 | 5 个 auth/click schema |
| `pyproject.toml` | 修改 | + `argon2-cffi` + `PyJWT` |
| `tests/test_auth.py` | 新增 | 14 case，覆盖哈希/JWT/过期/错密钥/bearer 解析 |
| `tests/test_personalization.py` | 新增 | 11 case，覆盖参数抽取/click 增量/script 拼装 |
| `tests/test_suggest.py` | 新增 | 5 case，覆盖 α 混合/去重/截断 |
| `docs/sec6-summary.md` | 新增 | 本文 |

## 2. 关键决策

### 2.1 鉴权技术栈

- **argon2id**（`argon2-cffi`）哈希密码，抗 GPU 暴破强于 bcrypt
- **JWT HS256** 无状态，默认 7 天过期；不上 refresh token（课程作业够用）
- 匿名搜索仍允许：`get_current_user_optional` 不抛 401；β 只在登录时启用
- `JWT_SECRET` 走 env，dev 默认 32+ 字节凑 RFC 7518 推荐长度（消除 InsecureKeyLengthWarning）

### 2.2 PersonalBoost 实现走 ES Painless

排序公式补全为：

```
score = (1-α) × [w1·BM25_norm + w2·PageRank]
      +  α    × [w3·Semantic × Obscurity]
      +  β    × [pb_w_src·pref_src + pb_w_tag·pref_tag + pb_w_clk·click_hit]
```

权重设计：`pb_w_src=0.4, pb_w_tag=0.4, pb_w_clk=0.2`（三项相加上限 1.0，再乘 β 给运行时调节）。

- **source 偏好**：Map<String,Double> 走 `((Map)params.pref_sources).containsKey(s)`，缺省 0
- **tag 偏好**：同上
- **点击命中**：List<String>，Painless `((List)params.click_set).contains(did)`，500 个 doc_id 内查找 O(n) 实测 ~3ms 无忧
- **缺省/退化**：β=0 或三项全空 → script 走 `double pb_term = 0.0;` 分支，不影响公式其他项

### 2.3 在线学习仅做加权 bump，不训模型

每次 `/feedback/click`：

- `preferred_sources[source] *= 1.02`（指数 bump），整体最大值过 1 时归一防爆炸
- `preferred_tag_weights[tag]` 同上
- `click_doc_ids` 入末尾（重复则移到末尾），上限 500 FIFO
- `click_history` 入末尾，上限 200，附带 dwell_ms / query

不引入用户兴趣向量×doc embedding 这条路径——一是 embedding 字段尚未全量回写（见 §4），二是评测前不引入未必必要的复杂度（评测后视效果决定）。

### 2.4 参数优先级：URL > 用户档案 > 全局默认

`/search` 的 `alpha/beta` 缺省时自动取 `user.default_alpha/default_beta`。
匿名用户档案为空 → `alpha=0, beta=0`，即纯 BM25+PR 行为。

### 2.5 联想路径：放弃 ES completion 子字段

设计阶段同意"completion 子字段重建索引"，实现时改用 **`match_phrase_prefix` + MongoDB query_log 聚合**：

- 等同前缀补全功能，**无须 reindex 96k 文档**（避免连带 PageRank/embedding 重灌）
- ES 端：`match_phrase_prefix` 在 `title^3 / title.en / title.cjk` 三个子字段都跑
- Mongo 端：`query_log` 按 `^q$prefix` 正则筛最近 5000 条，按频次排
- 语义路径走 ES `knn` query against `embedding` 字段（M5 已建好的 dense_vector），取 top 50 后砍最热门 5%

后续若实测前缀响应 > 50ms 才考虑专用 `isr_query_suggest` 索引 + `completion` 类型。当前规模够。

### 2.6 Suggest 降级

`/suggest?alpha=1`，但 embedder 未就绪 / embedding 字段空 → b_sem 返回空 → 若按公式 (1-α)×A + α×B = 0，所有结果归 0。改为：**b_sem 空时把 effective_alpha 视为 0**，A 路独立工作。

## 3. 实跑结果

### 3.1 测试覆盖

| 模块 | 用例数 | 状态 |
|---|---|---|
| `test_auth` | 14 | ✓ |
| `test_personalization` | 11 | ✓ |
| `test_suggest` | 5 | ✓ |
| 全量（含 M0-M5） | 57 | ✓ |

### 3.2 端到端冒烟：注册 → 登录 → /me

```
POST /auth/register {email, password, preferred_sources={fandom:.6,wiki:.4}, default_beta:1.0}
→ 201 + {access_token, user_id="u_xxx"}
GET /auth/me with Bearer → 200 profile
GET /auth/me without Bearer → 401
POST /auth/login wrong pw → 401
POST /auth/register dup email → 409
PATCH /auth/me {default_alpha:.6} → 200 + 更新落盘
```

### 3.3 端到端冒烟：PersonalBoost 排序变化（`q=Luffy, alpha=0`）

| 场景 | top-1 | score |
|---|---|---|
| 匿名（β=0） | fandom · Luffy, Law | 0.7662 |
| 登录用户 β=1，pref_sources={fandom:.6,wiki:.4} | fandom · Luffy, Law | **1.0062** |
| 登录但 URL `beta=0` | fandom · Luffy, Law | 0.7662 |
| 点击 wiki/Monkey D. Luffy 后再搜 | **wiki · Monkey D. Luffy** | **1.153** |

第 4 个场景验证：click_set 命中（+0.2 boost）+ wiki 权重从 0.4 bump 到 0.408（+0.40·0.408 ≈ 0.163），把原本排第 5 的 wiki 词条直接顶到第 1。

### 3.4 端到端冒烟：联想

`q=lu`（embedder 未触发数据，b_sem 空 → 降级到 A 路）：

| α | top-3 |
|---|---|
| 0 | history·Luffy / history·luffy gear / title·Lucky Luke |
| 0.5 | 同上（embedding 缺失，effective_alpha=0） |
| 1.0 | 同上 |

`q=monk, α=0`：title·Agnes Monkleigh / Drunk Monks / Headless Monks ... 前缀路径工作正常。

中文 `q=路飞, α=0.3`：返回空。原因数据侧：query_log 无中文历史 query；title 字段大部分英文，cjk 子字段在该词上无命中。等中文 fandom/wiki 数据进一步丰富 + embedding 写回后会改善。

### 3.5 性能（warm，5 次平均）

| 路径 | 延迟 | 备注 |
|---|---|---|
| `/auth/register` | 280 ms | argon2 哈希主导（time_cost=2 默认） |
| `/auth/login` | 270 ms | 同上 |
| `/auth/me` | 8 ms | Mongo find_one |
| `/search`（β=0） | ~45 ms | 与 M5 同档 |
| `/search`（β=1，click_set 1 个） | ~50 ms | Painless 多算 ~5ms |
| `/feedback/click` | 35 ms | ES get + Mongo update |
| `/suggest`（A 路） | ~28 ms | Mongo 正则 + ES match_phrase_prefix |
| `/suggest`（A+B） | ~35 ms | 加 kNN（当前 embedding 空，~7ms 无效但扫了） |

## 4. 已知坑 & 解决记录

| 现象 | 根因 | 解决 |
|---|---|---|
| `InsecureKeyLengthWarning` HMAC key < 32 bytes | 默认 dev SECRET 太短 | 默认值改 32+ 字节 |
| Pydantic `EmailStr` 拉新依赖 `email-validator` | 不必要 | email 字段用 `str` + Field 长度约束 |
| `/auth/login` 邮箱不存在 vs 密码错误 | 错误信息泄露用户存在性 | 统一返回 "invalid credentials" 避免枚举 |
| `/suggest?alpha=1` 返回全 0 分 | b_sem 空时 (1-α)·A=0 抹平 | effective_alpha 在 b_sem 空时强制 0 |
| `embedding` 字段一篇都没写 | M5 报告 §3.1 标注"持续中"但实际未跑完 | 不在 M6 范围；联想 + α 路径已有降级，不阻塞 |
| `pkill uvicorn` 在 zsh 子 shell 退出码 144 | 进程死了 shell 还在等管道，无害 | 忽略，验证用 `pgrep` 确认 |

## 5. 推迟到 M7+ 的项

- **前端 UI**（M7）：登录框 / α+β 双 slider / 联想下拉 / 点击埋点回调
- **用户兴趣向量 × doc embedding**：等 embedding 写回 + 评测决定是否叠加到 PB
- **专用 `isr_query_suggest` 索引** + `completion` 类型：等前缀延迟 > 50ms 再做
- **kNN ANN 召回换 `/search` 主路径的语义项**：M5 公式仍走 script_score 全表扫，α 高场景下 kNN 更快
- **dwell_ms 加权**：当前 click 一律 +0.2，后续可按 dwell 时长分级
- **refresh token**：课程作业可不做

## 6. 端到端冒烟脚本

```bash
docker compose up -d
export BGE_M3_MODEL_PATH=/home/lumine/model/bge-m3  # 可选；缺失走降级
uvicorn api.main:app --port 8000 &
BASE=http://127.0.0.1:8000

# 1) 注册 + 登录
EMAIL="demo_$(date +%s)@x.com"
TOK=$(curl -sS -X POST $BASE/auth/register -H 'content-type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"hunter22\",\"preferred_sources\":{\"fandom\":0.6,\"wiki\":0.4},\"default_alpha\":0.3,\"default_beta\":1.0}" \
  | python -c "import json,sys;print(json.load(sys.stdin)['access_token'])")

# 2) 匿名 vs 登录搜索对比
curl -sS "$BASE/search?q=Luffy&alpha=0&size=3"
curl -sS "$BASE/search?q=Luffy&alpha=0&size=3" -H "authorization: Bearer $TOK"

# 3) 点击 + 再搜（看 click_set 命中上浮）
DID=$(curl -sS "$BASE/search?q=Luffy&size=20" | python -c "import json,sys;print(next(h for h in json.load(sys.stdin)['hits'] if h['source']=='wiki')['doc_id'])")
curl -sS -X POST $BASE/feedback/click -H "authorization: Bearer $TOK" \
  -H 'content-type: application/json' -d "{\"doc_id\":\"$DID\",\"query\":\"Luffy\",\"dwell_ms\":3000}"
curl -sS "$BASE/search?q=Luffy&alpha=0&size=5" -H "authorization: Bearer $TOK"

# 4) 联想（α 切换）
for a in 0 0.5 1.0; do
  echo "--- alpha=$a ---"
  curl -sS "$BASE/suggest?q=lu&alpha=$a&size=5" | python -m json.tool
done
```

## 7. 下一步（衔接 M7）

按 `design.md §7 — M7 前端打磨 + 联想 + 快照页 + 日志展示`：

- [ ] 前端选型确认（Vue3 + Vite 或 Streamlit）
- [ ] 登录注册页 + JWT 在 localStorage / cookie 的选型
- [ ] 搜索页：双 slider（α/β）+ 联想下拉 + 高亮 + 快照按钮 + 点击埋点
- [ ] 个人中心：interests / preferred_sources / preferred_tag_weights 可视化编辑
- [ ] 查询日志展示（已有 `/log/recent` 后端）
- [ ] 收尾跑 `indexer/embed.py` 把 96k 文档 embedding 灌齐，语义路径才能真正激活
