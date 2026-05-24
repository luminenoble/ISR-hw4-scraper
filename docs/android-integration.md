# Android 集成方案（Inkite 联动）

> 目的：把 ISR 检索 + 个性化反馈能力下沉为可被 Inkite Android 应用复用的服务层
> 上下文：
> - Inkite 简介 见 `docs/inkite.md`（创意写作 + 社区分享 + 折纸奖励）
> - ISR 当前实现：FastAPI + Vue3 web（`docs/sec1-summary.md` ~ `docs/sec7-summary.md`）
> - 起草日期：2026-05-24

## 1. 定位与边界

| 维度 | ISR（本仓库） | Inkite Android |
|---|---|---|
| 形态 | Web 检索引擎 + FastAPI 后端 | 移动 App（创作+社区） |
| 主用户场景 | "我要写之前考据角色" | "我要写、要发、要奖励" |
| ISR 在其中角色 | **主体功能** | **嵌入式工具**（灵感、查角色、插入引用） |
| 视觉调性 | 档案馆 · 衬线 · 粉蓝克制 | 折纸 · 温暖 · 游戏化 |

**核心原则**：**后端共享，前端各做各的**。Inkite 不嵌 ISR web，也不复制 ISR UI，而是用 ISR 的 REST API 自己原生实现。

## 2. 后端复用清单

ISR FastAPI 端点全部天然适配 Android 客户端（JSON over HTTPS + Bearer JWT）：

| 端点 | Android 用途 |
|---|---|
| `POST /auth/register` `POST /auth/login` | 复用同一套账号体系；Inkite 用户可"链接 ISR" |
| `GET /search` | 全文检索（重场景） |
| `GET /search/cards` | **移动端首选**：精简版，节省带宽 |
| `GET /suggest` | 写作时输入提示 / 灵感联想 |
| `POST /feedback/click` | 写作中插入引用 = 一次"click"，反向喂偏好 |
| `POST /feedback/event` | 移动端 5 指标埋点统一入口 |
| `GET /snapshot/{doc_id}` | 引用源页快照（Inkite 在引用脚注里链接） |
| `GET /auth/me` `PATCH /auth/me` | 个人偏好编辑（可与 Inkite 自有账号合并） |
| `GET /logs/me` `GET /logs/clicks/me` | 写作历史回顾 |

**M7 阶段已为移动端预埋**：
- `/search/cards` —— 移动端流量优化版（无 `<em>` 标签，单条 ~300B vs `/search` 单条 ~2KB）
- `/feedback/event` —— 通用埋点端点（5 指标统一）

## 3. ISR 在 Inkite 的三个嵌入点

### 3.1 自由创作模式 · 角色字典抽屉

写作页右侧抽屉（默认收起），唤出后是一个浮层搜索：

```
┌─────────────────────────────────────────────────────┐
│  正在写：                       ┃  角色字典 (drawer) │
│                                ┃                    │
│  路飞跳上栏杆，向远方眺望……      ┃  🔍 [Luffy_]      │
│                                ┃                    │
│  [光标]                        ┃  • Monkey D. Luffy │
│                                ┃    [wiki] [canon]  │
│                                ┃    [插入引用]       │
│                                ┃                    │
│                                ┃  • Luffy Taro      │
│                                ┃    [fandom][fanon] │
└────────────────────────────────┴────────────────────┘
```

- 调 `/search/cards?q=Luffy&size=6`
- 点击"插入引用"：在光标位置插入 `[Luffy](isr://doc/<doc_id>)` 这样的标记
- 自动调 `/feedback/click` —— 把"插入"视为强反馈（dwell_ms 设为 -1 表"已采纳"）

### 3.2 官方挑战 · 三词种子触发

Inkite 的"官方挑战"由系统每天发布三个提示词。当用户开始挑战：

1. 取三个词依次喂给 `/suggest?q=<词>&alpha=1.0`（高发散度）
2. 把三组返回里 kind='semantic' 的小众语义近邻**交叉混合**——比如"剑客 + 沙漠 + 钟楼"返回的语义近邻可能是某个 fandom 里的偏门角色
3. 给用户 3 张"灵感卡片"作为写作种子

后端零改动。

### 3.3 展览厅 · 收藏角色折纸

用户把搜过的角色"折成折纸"存进展览厅（Inkite 的奖励系统）：

- Android 端调用 `POST /feedback/click` 时附带 `query="__collected__"`
- 这样在 ISR 的 `users.click_history` 里可识别为"主动收藏"事件
- 展览厅展示时去 ISR `/search/cards?q=<title>` 拉最新标题/摘要展示

## 4. Android 技术栈推荐

| 层 | 选型 | 理由 |
|---|---|---|
| UI | **Jetpack Compose**（推荐）| 声明式，与 Vue3 心智一致；可定制远超 XML |
| 网络 | **Ktor Client** + **kotlinx.serialization** | 现代、Multiplatform-ready（未来 iOS） |
| 异步 | Coroutines + Flow | 联想接口 `debounce` 天然适配 |
| 本地存储 | **Room** | 缓存搜索结果 + 离线点击事件队列 |
| 后台任务 | **WorkManager** | 反馈/埋点离线队列必备 |
| 图片 | Coil | Inkite 折纸 AI 图加载 |
| DI | Hilt | 标配 |
| 鉴权 | EncryptedSharedPreferences 存 JWT | 防被其他 App 读 |

## 5. 关键工程实践

### 5.1 共享 design tokens（跨端单一真实来源）

把 `frontend/src/styles/tokens.css` 中色板/字号/间距抽到根 `shared/design-tokens.json`：

```json
{
  "color": {
    "inkBlue": "#3B5A8E",
    "stampRose": "#C26A75",
    "paper": "#FBF7F0"
  },
  "font": {
    "display": ["Fraunces", "Noto Serif SC"],
    "mono": ["JetBrains Mono", "IBM Plex Mono"]
  },
  "spacing": { "1": 4, "2": 8, "3": 12, "4": 16 }
}
```

- Web 端：Vite plugin 构建时读 JSON → 生成 CSS variables
- Android 端：Gradle plugin 读同一 JSON → 生成 `Color.kt` / `Typography.kt`

改一处 = 两端同步。**当前 M7 未实施，建议 M8 末或后续启动时立即做**（成本 1 小时，长期收益高）。

注意：Android Inkite 自己的"折纸"主题会**覆盖**这些 token 的部分配色（如不用 `--stamp-rose`，改用赭橘 `#D89B6C`），但字体栈和间距系统共享。

### 5.2 反馈埋点的离线韧性

Web 端 `telemetry.ts` 调 `fetch /feedback/event` 失败即吞掉。Android 必须更稳：

```kotlin
@Entity
data class PendingEvent(
  @PrimaryKey(autoGenerate = true) val id: Long = 0,
  val kind: String,
  val payloadJson: String,
  val ts: Long,
)

fun trackEvent(kind: String, payload: Map<String, Any>) {
  pendingEventDao.insert(PendingEvent(...))
  WorkManager.getInstance(ctx).enqueue(SyncEventsWorker.request)
}

// SyncEventsWorker: 网络可用时批量 POST /feedback/event，失败退避重试
```

WorkManager 兜底退避策略、网络感知、电量优化。

### 5.3 联想 API 的移动端缓存

```kotlin
@Dao
interface SuggestCacheDao {
  @Query("SELECT * FROM suggest_cache WHERE prefix = :p AND alpha_bucket = :a AND ts > :exp")
  suspend fun get(p: String, a: Int, exp: Long): SuggestCache?
}

private fun alphaBucket(a: Double) = when {
  a < 0.34 -> 0
  a < 0.67 -> 1
  else -> 2
}

class SuggestRepo(private val api: IsrApi, private val cache: SuggestCacheDao) {
  fun suggest(q: String, alpha: Double): Flow<List<Suggestion>> = flow {
    val bucket = alphaBucket(alpha)
    val cached = cache.get(q.lowercase(), bucket, System.currentTimeMillis() - TTL_5MIN)
    if (cached != null) emit(cached.suggestions)
    val fresh = api.suggest(q, alpha)
    cache.upsert(q.lowercase(), bucket, fresh.suggestions)
    emit(fresh.suggestions)
  }
}
```

- α 用三档桶 `(low/mid/high)` 替代连续值，缓存命中率高
- 5 分钟 TTL，先回缓存 + 后台刷新（stale-while-revalidate）
- debounce 300ms（web 用 180ms，移动端要更宽容）

### 5.4 字段裁剪与流量

详细见 `/search/cards`（M7 已实现）。Android 默认全部用 cards 版本，仅在"详情页"用全字段 `/search`（如未来加 `/doc/{id}`，更优）。

### 5.5 折纸卡 UI（Compose 实现要点）

每张搜索结果是可翻面的折纸卡：

```kotlin
@Composable
fun OrigamiResultCard(hit: HitCard, onClick: () -> Unit, onInsert: () -> Unit) {
  var flipped by remember { mutableStateOf(false) }
  val rotation by animateFloatAsState(if (flipped) 180f else 0f, tween(450))
  Box(modifier = Modifier
    .graphicsLayer { rotationY = rotation; cameraDistance = 12 * density }
    .clickable { flipped = !flipped }
  ) {
    if (rotation <= 90f) FrontFace(hit)
    else BackFace(hit, modifier = Modifier.graphicsLayer { rotationY = 180f }, onInsert)
  }
}
```

- 正面：标题 + source badge + tag
- 翻面：snippet + 操作（插入引用 / 收藏 / 快照）
- 翻面动作本身是"折"的隐喻

### 5.6 鉴权一致性

ISR 当前 JWT 7 天过期。Inkite 自有账号系统需要做账户合并：

**推荐流程**：
1. Inkite 注册账号（自有用户系统）
2. 设置中"链接 ISR"按钮，OAuth-style 跳转到 ISR `/auth/login`
3. ISR 颁发 JWT 回传到 Inkite，Inkite 存储为"ISR session"独立于自身 session
4. 调 ISR API 时附带 ISR 的 JWT

**长期更好的方案**：把账号系统提取为独立 `auth-service`，ISR 和 Inkite 都走它；当前 ISR 用户量小，**先不做**，等 Inkite 真正上线再迁。

## 6. 后端要补的最小改动（建议 M8 顺手做）

| 端点 | 用途 | 工作量 |
|---|---|---|
| `GET /doc/{id}` | 单文档完整字段（移动详情页 + web 详情页都需要） | 30 min |
| `POST /feedback/insert` | "插入引用"专用端点（与点击区分） | 20 min |
| `GET /search/cards` 加 `format=mini` 选项 | 进一步裁剪到 title+source（150B） | 10 min |
| HEAD `/snapshot/{id}` | 移动端预检快照是否存在 | 10 min |

不在 M7 范围，但提前列出避免遗忘。

## 7. 集成形态对比

| 方案 | 优点 | 缺点 | 推荐 |
|---|---|---|---|
| WebView 直接嵌入 ISR web | 0 工作量 | 调性冲突（档案馆≠折纸）、离线烂、JS↔Native 桥麻烦 | ✗ |
| 全原生 Compose + Ktor | 体验最好、可深度定制成折纸 | 工作量大（~3 周） | ✓✓ **推荐** |
| Compose Multiplatform（iOS 同时出） | 长期收益最大 | 学习曲线 + 工具链尚不稳 | 视团队 |
| Flutter | 跨端 + 性能 OK | 与 Inkite 已有 Kotlin 栈不一致 | ✗ |

## 8. 路线图

| 阶段 | 内容 | 估时 |
|---|---|---|
| **A**（与 ISR M8 并行） | 后端补 `/doc/{id}` + `/feedback/insert` + design-tokens.json | 1 天 |
| **B** | Android 项目脚手架 + Ktor + 鉴权 + `/search` 跑通 | 2 天 |
| **C** | 自由创作模式 · 角色字典抽屉 UI + `/feedback/click` 接通 | 2 天 |
| **D** | 官方挑战 · 三词种子触发 + `/suggest?alpha=1` | 1 天 |
| **E** | 展览厅 · 角色收藏接入 + 离线队列 | 2 天 |
| **F** | 全链路埋点（5 指标）+ WorkManager 韧性测试 | 1 天 |

总计 ~9 天独立开发，可以与 ISR M8 评测报告并行。

## 9. 边界与不做的事

- **不做**：把 Inkite 的写作/社区/折纸功能塞进 ISR web。两边都保持自己的核心场景。
- **不做**：跨端 UI 复用层。Compose 和 Vue 共用 design tokens 即可，组件各自实现。
- **不做**：把 ISR 用户群与 Inkite 用户群强行合并。两边都是独立账号，链接关系按需建立。
- **不做**：在 ISR web 端引入 Inkite 风格的折纸装饰。视觉调性独立。

## 10. 风险

| 风险 | 缓解 |
|---|---|
| ISR 后端单实例承载 Inkite 上线后流量激增 | 当前 docker-compose 单机 + ES 单分片够 1k QPS；超过后加 ES 多副本 + uvicorn 多 worker |
| JWT 7 天过期 → 移动端断后台重启需重新登录 | M8 加 refresh token 端点（30 分钟内变更）|
| design tokens 漂移导致两端视觉断裂 | 起步阶段约定 PR 必须同时改 JSON + 跑两端 build |
| 中文 query 召回差 | 等 embedding 全量回写 + 加中文 query_log 训练联想 |
