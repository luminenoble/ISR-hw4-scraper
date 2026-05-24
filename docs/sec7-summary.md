# Sec.7 前端 + 联想 + 快照页 + 日志展示（M7 阶段）

> 对应里程碑：`design.md §7 — M7 前端打磨 + 联想 + 快照页 + 日志展示`
> 完成日期：2026-05-24
> 上游依赖：`docs/sec6-summary.md`（用户系统 + 个性化 + 联想后端已就绪）
> 视觉规范：`docs/m7-frontend-design.md`（粉蓝 · 档案馆风）

## 1. 交付物清单

### 后端补充（M7-1）

| 路径 | 性质 | 作用 |
|---|---|---|
| `api/routers/log.py` | 修改 | 加 `GET /logs/me`、`GET /logs/clicks/me`（JWT 鉴权） |
| `api/routers/feedback.py` | 修改 | 加 `POST /feedback/event` 通用埋点（5 指标统一入口） |
| `api/routers/search.py` | 修改 | 加 `GET /search/cards` 移动端精简版（去 `<em>`、裁字段） |
| `api/schemas.py` | 修改 | 加 `EventRequest / HitCard / SearchCardsResponse` |

### 前端（M7-2/3/4）

| 路径 | 性质 | 作用 |
|---|---|---|
| `frontend/package.json` | 新增 | Vue3 + vue-router + Vite + TS |
| `frontend/vite.config.ts` | 新增 | `/api` 反代到 FastAPI |
| `frontend/tsconfig.json` | 新增 | strict TS + verbatimModuleSyntax |
| `frontend/index.html` | 新增 | Google Fonts: Fraunces + Crimson Pro + JetBrains Mono + Noto Serif SC |
| `frontend/public/favicon.svg` | 新增 | 钢笔蓝 "A" 图标 |
| `frontend/src/styles/tokens.css` | 新增 | 全部设计 token（色板/字体/间距/半径/阴影） |
| `frontend/src/styles/base.css` | 新增 | Reset + 全局组件样式（button/input/badge/chip/em 高亮） |
| `frontend/src/lib/api.ts` | 新增 | REST 客户端，所有端点封装 + 自动注入 JWT |
| `frontend/src/lib/auth.ts` | 新增 | JWT 存 localStorage + reactive 登录态 |
| `frontend/src/lib/telemetry.ts` | 新增 | 5 指标埋点（latency/empty/click/tuning/filter） |
| `frontend/src/router.ts` | 新增 | 6 路由（含 authed 守卫） |
| `frontend/src/main.ts` | 新增 | app 入口 |
| `frontend/src/App.vue` | 新增 | masthead + 导航 + footer 外壳 |
| `frontend/src/pages/Login.vue` | 新增 | 双栏（brand panel + form） |
| `frontend/src/pages/Register.vue` | 新增 | 两步：账号 + 冷启动偏好 |
| `frontend/src/pages/Search.vue` | 新增 | **核心**：搜索栏 + 联想 + α/β + source filter + 结果列 + 分页 |
| `frontend/src/pages/Detail.vue` | 新增 | 单文档元数据 + 同 source 相关 + 操作 |
| `frontend/src/pages/Profile.vue` | 新增 | interests / pref_sources / pref_tags / 默认 α-β 编辑 |
| `frontend/src/pages/Log.vue` | 新增 | 双 tab（搜索历史 / 点击历史）按日期分组 |
| `frontend/src/components/SuggestDropdown.vue` | 新增 | 三类标记（▸ 历史 / · 标题 / ◇ 语义） |
| `frontend/src/components/ResultEntry.vue` | 新增 | 档案条目卡（左侧 001/边线 + 标题/snippet/元数据/操作） |
| `frontend/src/components/TuningPanel.vue` | 新增 | 折叠面板含 α slider（蓝→粉渐变轨道）+ β + 4 个 source checkbox |
| `docs/sec7-summary.md` | 新增 | 本文 |
| `docs/android-integration.md` | 新增 | Android 集成方案 |

## 2. 关键决策

### 2.1 视觉延续 m7-frontend-design.md，不为 Inkite 改向

用户明确要求：M7 的 ISR web 风格保持档案馆/粉蓝/极简，与未来 Inkite 移动端解耦——两套设计语言共享后端 API 和品牌色（钢笔蓝），其他自由发挥。Inkite 的折纸风格只影响 Android 端实现，本期不动 web。

### 2.2 Vite proxy 替代 CORS

dev 模式 `vite --port 5173` 走 `proxy /api → 127.0.0.1:8000`，前端 fetch 直接写 `/api/...`，避开 CORS 调试期 preflight、生产环境上线时改 nginx 反代即可（路径不变）。

### 2.3 TS strict + vue-tsc + 无组件库

刻意不引入 Element Plus / Vuetify：
- 设计文档已经给出色板和组件规则，UI 库会强加自己的 Material/Ant 风格冲淡档案馆主题
- 当前 5 页 + 3 组件总共 ~95KB main bundle，引入组件库直奔 300KB+

代价：所有交互组件手写。收益：完全可控、bundle 小、与设计 100% 一致。

### 2.4 telemetry 火烧后忽略

`telemetry.ts` 5 个 trackXxx 函数全部 `.catch(() => {})`，埋点失败不影响主流程。后端 `/feedback/event` 用 204 No Content 表示"已收"。

### 2.5 搜索结果点击 = 路由跳详情 + 调用 `/feedback/click`

`ResultEntry` 的"详情" / "快照"按钮都触发 `emit('click-result')`，父组件 `Search.vue`：
1. 调 `telemetry.trackClick(doc_id, rank, query)` 写 events 集合
2. 调 `api.click({doc_id, query})` 写 users.click_history + click_doc_ids（β·PersonalBoost 用）

埋点和反馈是**两条独立链路**：埋点匿名也发（events 表），反馈仅登录用户调（users 表）。

### 2.6 默认 α/β 优先级：用户档案 > URL 查询 > 全局默认

`Search.vue` `onMounted` 时如已登录，从 `/auth/me` 拉用户档案覆盖本地 ref；同时 search router 后端也用同样优先级保证服务端一致。前端只是更早把 slider 显示到正确位置。

### 2.7 联想路径降级

`onInput` 防抖 180ms 调 `/suggest?alpha=<当前>`。后端在 embedder 未就绪或 embedding 字段空时自动把 effective_alpha 视为 0（M6-3 已做），前端无感知；slider 在 1.0 时仍能看到前缀结果。

### 2.8 source filter 简化为单选时才生效

前端 4 个 source checkbox 任意组合，但后端 `source` 参数是单值过滤——目前实现：勾全部或勾 0 → 不传 source；只勾 1 个 → 传该值；勾 2-3 个 → 视为不传（无法精确表达 OR）。

M8 评测后视用户反馈：若需要多选支持，后端改为 `terms` query，前端传 list 即可。

## 3. 实跑结果

### 3.1 端到端冒烟（Vite proxy 链路）

```
[/api/health]      → {"ok":true,"index":"isr_pages","doc_count":96109}
[/api/search]      → total=6165 took=25ms top="Luffy, Law"
[/api/suggest]     → history|Luffy / history|luffy gear / title|Lubdan
[/api/auth/register] → JWT
[/api/auth/me]     → user_id="u_7HNyeje7E2ym" default_alpha=0.5 default_beta=1.0
```

### 3.2 构建产物

| chunk | size | gzip |
|---|---|---|
| `index-xxx.js`（vendor + 入口） | 95.05 kB | 37.25 kB |
| `Search-xxx.js` | 8.61 kB | 3.76 kB |
| `Profile-xxx.js` | 4.77 kB | 1.86 kB |
| `Register-xxx.js` | 2.91 kB | 1.66 kB |
| `Detail-xxx.js` | 2.86 kB | 1.47 kB |
| `Log-xxx.js` | 2.85 kB | 1.29 kB |
| 5 页 CSS 合计 | 13.10 kB | 4.13 kB |
| `index-xxx.css`（基础 + 全局） | 5.69 kB | 1.84 kB |

总 JS+CSS 约 **140 kB / gzip 50 kB**，无 UI 库的回报。

### 3.3 类型检查

`vue-tsc --noEmit` exit=0。strict TS + verbatimModuleSyntax 全部通过。

### 3.4 字体加载

Google Fonts 一次性 preconnect + 单 link，Fraunces variable opsz axis 加 Crimson Pro 400/600 加 JetBrains Mono 400/500 加 Noto Serif SC 400/600，总下载 ~280 KB（首次访问），缓存后 0 字节。

## 4. 实现细节亮点

### 4.1 ResultEntry 的"档案条号"
```html
<div class="gutter">
  <div class="num mono">{{ String(index).padStart(3, '0') }}</div>
  <div class="bar"></div>  <!-- 2px 垂直线，从条号延伸到卡片底 -->
</div>
```
0-pad 3 位 mono 数字 + 一根 2px 钢笔蓝灰垂直分隔——视觉上把每条结果钉成"档案册一页"。

### 4.2 α slider 的轨道渐变
```css
.slider.alpha {
  background: linear-gradient(to right, var(--ink-blue-soft), var(--stamp-rose-soft));
  -webkit-appearance: none;
}
.slider.alpha::-webkit-slider-thumb {
  width: 14px; height: 14px;
  background: var(--ink);
  border-radius: 0;  /* 方角 thumb，强化档案/印章感 */
}
```
轨道颜色直观表达"权威↔二创"的连续光谱，thumb 是方形钢笔蓝拖块。

### 4.3 snippet 高亮
后端返回的 `<em>` 标签在前端 `v-html` 渲染，全局 `:deep(em)` 样式给朱印粉底色：
```css
em { background: var(--stamp-rose-soft); padding: 0 2px; font-style: normal; }
```
与"印章"主题一致，不加粗（避免破坏 Crimson Pro 阅读节奏）。

### 4.4 双横线 detail 标题
```css
.double {
  border-top: 1.5px solid var(--ink);
  border-bottom: 1.5px solid var(--ink);
  height: 4px;
}
```
一道 4px 高的双线，详情页 H1 下方——一眼"正式档案"。

## 5. 已知坑 & 解决记录

| 现象 | 根因 | 解决 |
|---|---|---|
| `setTimeout` 在 vue template 中 TS 报错 | template 上下文不含 globalThis 的 setTimeout | 提取为 `onBlurDelay` 方法 |
| Pydantic `Annotated` 在 deps.py 未导入 | M6-1 漏 import | M6-1 已修；M7 沿用 |
| Vite proxy 后 fetch 走 `/api/*`，生产部署需另设反代 | dev/prod 不一致 | 上线时 nginx `location /api { proxy_pass http://localhost:8000; }` 即可，路径零改 |
| Google Fonts 首次访问加载慢 | CDN 在境内可能延迟 | 留 fallback 链：`'Noto Serif SC' → Georgia → serif`，本地无 Fraunces 也能读 |
| source filter 多选时不能精确表达 | 后端 `source` 单值过滤 | 暂当无过滤；M8 视需要改 `terms` query |
| 详情页正文是空的（只有 lede） | 后端 `/doc/{id}` 端点未实现 | M7 占位；M8 补 |

## 6. 推迟到 M8 的项

- `GET /doc/{id}`：让详情页能展示完整 body（非仅 lede 占位文字）
- 多选 source 过滤的 `terms` query
- 离线 PWA 缓存搜索结果
- 中文 query 联想效果：embedding 跑完后再做 case study
- 评测报告（M8 主任务）

## 7. 端到端冒烟脚本

```bash
# 1) 起后端 + 前端 dev server
docker compose up -d
source .venv/bin/activate
export BGE_M3_MODEL_PATH=/home/lumine/model/bge-m3   # 可选
uvicorn api.main:app --port 8000 &

cd frontend
npm install                 # 首次
npm run dev                 # 起 vite，监听 :5173

# 2) 浏览器打开 http://127.0.0.1:5173
# → 重定向到 /search
# → 顶部"登录"进入 /login
# → 点"注册"进入两步注册（账号 → 冷启动偏好）
# → 提交后自动登录 → 跳回 /search
# → 输入 "Luffy" 看联想下拉
# → 展开调节面板拖 α slider
# → 点详情/快照按钮（埋点 + 反馈双链路）
# → 顶栏"档案"→ /me 编辑偏好
# → 顶栏"日志"→ /log 查看搜索与点击历史

# 3) 生产构建
npm run build               # → dist/
npx vite preview --port 5173  # 验证 dist 产物
```

## 8. 下一步（衔接 M8）

按 `design.md §7 — M8 联调 / 测试 / 评测报告`：

- [ ] `GET /doc/{id}` 端点 + 详情页正文
- [ ] 评测脚本：embedding-on vs embedding-off 的 NDCG/MRR 对比
- [ ] 评测脚本：α 0/0.3/0.7/1 各档下的结果差异
- [ ] 评测报告：6 种查询全部走通的 case study
- [ ] embedding 收尾确认（背景任务跑完 ~70 min）
- [ ] 跨端集成方案落实（见 `docs/android-integration.md`）
