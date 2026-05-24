# M7 前端视觉设计文档

> 视觉概念：**「角色档案馆」(Character Dossier Archive)**
> 隐喻：文学研究档案室的数字化身——羊皮纸感的米白底、衬线主导、左右留白如旧书页边、用钢笔蓝与朱印粉做强调
> 起草日期：2026-05-24（M7 启动前敲定）

## 1. 设计原则

避开常见 AI slop：
- 不用紫色渐变 / Inter / Roboto / Space Grotesk
- 不用圆角卡片网格
- 不用扁平 Material 配色
- 用衬线 + 编目 mono + 不对称排版做差异化

## 2. 色板

### 基础色
| token | hex | 用途 |
|---|---|---|
| `--paper` | `#FBF7F0` | 主背景，旧纸感米白 |
| `--paper-2` | `#F4EDE0` | 次级背景（卡片、面板） |
| `--ink` | `#1E2233` | 正文，带蓝调的深墨 |
| `--ink-2` | `#4A5066` | 次级文字 |
| `--rule` | `#D8CFC0` | 分隔线、边框 |

### 主色（双主色，3:7 分布）
| token | hex | 用途 |
|---|---|---|
| `--ink-blue` | `#3B5A8E` | **主色**：链接、主操作、α slider 左端 |
| `--ink-blue-soft` | `#A4B8D8` | 主色弱化：按钮 hover 底、tag bg |
| `--stamp-rose` | `#C26A75` | **辅色**：强调、错误、α slider 右端、score 高分 |
| `--stamp-rose-soft` | `#E8C2C6` | 辅色弱化：高亮 bg、active chip |

### 语义色
| token | hex |
|---|---|
| `--ok` | `#5C8A6E` |
| `--warn` | `#B8893A` |
| `--err` | `#A84A55` |
| `--info` | `#3B5A8E` |

### Source / Tag 专色
| token | hex |
|---|---|
| `--src-fandom` | `#C26A75` |
| `--src-wiki` | `#3B5A8E` |
| `--src-reddit` | `#B8893A` |
| `--src-document` | `#5A5A5A` |
| `--tag-canon` 描边 | `#3B5A8E` |
| `--tag-fanon` 描边 | `#C26A75` |
| `--tag-meta` 描边 | `#5C8A6E` |
| `--tag-crossover` 描边 | `#7C5A8E` |

对比度全部 ≥ WCAG AA：ink/paper 13.2:1，ink-blue/paper 7.1:1，stamp-rose/paper 4.6:1。

## 3. 字体栈

```css
--font-display: 'Fraunces', 'Noto Serif SC', Georgia, serif;
--font-body:    'Crimson Pro', 'Noto Serif SC', Georgia, serif;
--font-mono:    'JetBrains Mono', 'IBM Plex Mono', ui-monospace, monospace;
```

| 用途 | 字体 | 选择理由 |
|---|---|---|
| 大标题、品牌名 | Fraunces (variable) | 现代衬线，opsz/SOFT/WONK 三轴可玩 |
| 正文、结果标题 | Crimson Pro | 古典衬线，长篇阅读舒适 |
| 数字、元数据、tag | JetBrains Mono | 像档案编号 |
| 中文 | Noto Serif SC | 与衬线英文匹配 |

### 字号刻度（base 16px）
| token | rem | px |
|---|---|---|
| `--text-xs` | 0.75 | 12 |
| `--text-sm` | 0.875 | 14 |
| `--text-base` | 1 | 16 |
| `--text-lg` | 1.125 | 18 |
| `--text-xl` | 1.375 | 22 |
| `--text-2xl` | 1.875 | 30 |
| `--text-3xl` | 2.625 | 42 |
| `--text-4xl` | 3.75 | 60 |

## 4. 间距 / 半径 / 阴影

```css
--sp-1: 4px;  --sp-2: 8px;  --sp-3: 12px;
--sp-4: 16px; --sp-5: 24px; --sp-6: 32px;
--sp-8: 48px; --sp-10: 64px; --sp-12: 96px;
```

- **半径**：基本不用圆角（直角强化档案/印章感）
  - input/button: 2px；avatar: 9999px；chip/tag: 0
- **阴影**（极克制，单档）：
  ```css
  --shadow-paper: 0 1px 0 #E5DBC9, 0 8px 24px -12px rgba(30,34,51,.18);
  ```
- **内容宽**：主页面 920px；详情页正文 68ch

## 5. 各页面 wireframe

### 5.1 登录 / 注册（双栏）
- 左面板 brand：巨型 Fraunces "ISR." + tagline + 装饰短线
- 右面板表单：单列、generous spacing、钢笔蓝 submit
- 注册第 2 步冷启动：interests chip 多选 + sources slider 3 行

### 5.2 主搜索页（核心）
- 顶部 masthead：logo + 导航 + 用户态
- 搜索栏：Fraunces 22px + 实时联想下拉
- 联想下拉：三类分组（▸ history / · title / ◇ semantic）
- 调节面板（折叠）：α slider（蓝→粉渐变轨道）+ β slider + source checkbox
- 结果列表：每条左侧"档案条号" `001` + 垂直分隔线，标题用 Fraunces 22px，snippet 朱印粉高亮
- 元数据 mono 小字：`score 1.153 · pr 0.00184 · fetched 2026-04`

### 5.3 详情页
- 双横线标题（`border-top + border-bottom` 各 1.5px）
- 元数据列表 mono（key 左对齐）
- 正文 max-width 68ch / line-height 1.75
- 右侧浮动面板：相关档案 + 操作（快照/原始链接/反馈）

### 5.4 个人档案
- 顶部 avatar + email + uid + 注册日期
- 兴趣作品 chip cloud（可增删）
- 站点偏好 bar：mono 名 + 进度条 + slider + 数值
- 标签偏好 bar：同上
- 默认 α/β slider
- 危险区按钮

### 5.5 查询日志
- 双 tab：搜索历史 / 点击历史
- 时间用 mono 左对齐，垂直线分隔时间与内容
- 日期分组 `── 2026-05-23 ──`

## 6. 装饰与微交互（克制使用）

仅 3 处装饰：
1. 登录页 brand 区域：细线条羽毛笔图（< 80px）
2. 搜索框 focus：底边 1px → 1.5px ink-blue，0.15s 过渡
3. chip 选中 active：内阴影一道钢笔蓝印章

禁止：bounce、ripple、渐变背景（α slider 例外）、emoji 装饰、skeleton loading。

可选纸张噪声纹理（背景 5% 透明度），做"老纸张"质感。

## 7. 可访问性

- 所有色对比度 ≥ WCAG AA
- `:focus-visible` 显式 `outline: 2px solid var(--ink-blue)`
- slider 键盘 ←/→ 调节，Shift 长按加大步长
- 联想下拉键盘导航 ↑↓Enter Esc
- 所有 mono 数字 `font-feature-settings: "tnum"` 等宽对齐

## 8. 响应式

```css
--bp-sm: 640px;
--bp-md: 960px;
--bp-lg: 1280px;
--bp-xl: 1600px;
```

手机端：调节面板默认折叠 · 联想下拉全屏 · 详情页右栏移到正文下方 · 结果卡条号缩到 2 位。

## 9. 指标埋点（5 个）

| 指标 | 时机 | 数据 |
|---|---|---|
| 响应延迟 | 搜索返回 | `took_ms` |
| 点击率 | 点击结果 | doc_id + rank + query + α + β |
| α/β 调节频次 | slider 松手 | from, to, ts |
| 空结果率 | 搜索返回 | total === 0 |
| 平均 RR | 点击时 | 1 / rank |

统一 POST 到 `/feedback/event`（M7-1 已实现），异步不阻塞 UI。

## 10. 决策摘要（与默认方案的差异）

| 维度 | 默认 | 本方案 | 理由 |
|---|---|---|---|
| 字体 | Inter / Roboto | Fraunces + Crimson Pro + JetBrains Mono | 长文阅读舒适；档案隐喻 |
| 配色 | 鲜亮粉蓝 | 朱印粉 + 钢笔蓝（饱和度 ≤ 50） | 耐看，避免甜腻 |
| 卡片 | 圆角 + box-shadow | 方角 + 双横线 + 左侧档案条号 | 强化档案册隐喻 |
| slider | 单色 thumb | 两端图文 + 轨迹渐变（蓝→粉） | α 二元性视觉化 |
| 高亮 | 加粗 + 黄底 | 朱印粉底 + 正文字重 | 与印章主题一致 |
| 装饰 | 大量 micro-interaction | 仅 3 处过渡 | 工具型 UI，让用户聚焦内容 |
