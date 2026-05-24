<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { search, suggest, click, me } from '../lib/api'
import type { Hit, SearchResponse, Suggestion } from '../lib/api'
import { isLoggedIn } from '../lib/auth'
import {
  trackLatency, trackEmpty, trackClick,
  trackTuning, trackSourceFilter,
} from '../lib/telemetry'
import SuggestDropdown from '../components/SuggestDropdown.vue'
import ResultEntry from '../components/ResultEntry.vue'
import TuningPanel from '../components/TuningPanel.vue'

const router = useRouter()
const route = useRoute()

const q = ref('')
const alpha = ref(0.3)
const beta = ref(0.5)
const sources = ref<Record<string, boolean>>({ fandom: true, wiki: true, reddit: true, document: true, ao3: true })
const rating = ref('')      // '' = 不过滤；仅对 source=ao3 文档生效
const language = ref('')    // '' = 不过滤

const suggestions = ref<Suggestion[]>([])
const suggestVisible = ref(false)
let suggestTimer: number | null = null

const result = ref<SearchResponse | null>(null)
const loading = ref(false)
const error = ref('')

const page = ref(0)
const PAGE_SIZE = 10
const pageCount = computed(() => result.value ? Math.max(1, Math.ceil(result.value.total / PAGE_SIZE)) : 0)

onMounted(async () => {
  // 已登录则把默认 α/β 拉下来用作初始值
  if (isLoggedIn.value) {
    try {
      const u = await me()
      alpha.value = u.default_alpha
      beta.value = u.default_beta
    } catch { /* 忽略，使用默认 */ }
  }
  // 路由有 q 参数时复现搜索
  const initQ = route.query.q as string | undefined
  if (initQ) { q.value = initQ; runSearch() }
})

function buildSourceFilter(): string | undefined {
  // 只有部分勾选时传 source 参数（暂不支持多 source AND/OR，单选时生效）
  const selected = Object.entries(sources.value).filter(([, v]) => v).map(([k]) => k)
  if (selected.length === 0 || selected.length === Object.keys(sources.value).length) return undefined
  // 仅当只勾一个时才能精确过滤（后端 source 字段单值过滤）
  if (selected.length === 1) return selected[0]
  return undefined
}

async function runSearch(resetPage = true) {
  if (!q.value.trim()) return
  if (resetPage) page.value = 0
  loading.value = true
  error.value = ''
  suggestVisible.value = false
  try {
    const r = await search({
      q: q.value,
      size: PAGE_SIZE,
      from: page.value * PAGE_SIZE,
      source: buildSourceFilter(),
      alpha: alpha.value,
      beta: beta.value,
      rating: rating.value || undefined,
      language: language.value || undefined,
    })
    result.value = r
    trackLatency(q.value, r.took_ms, r.total)
    if (r.total === 0) trackEmpty(q.value)
    router.replace({ path: '/search', query: { q: q.value } })
  } catch (e: any) {
    error.value = e?.detail || e?.message || '搜索失败'
  } finally {
    loading.value = false
  }
}

function onBlurDelay() {
  window.setTimeout(() => { suggestVisible.value = false }, 120)
}

function onInput() {
  if (suggestTimer) clearTimeout(suggestTimer)
  if (!q.value.trim()) { suggestions.value = []; suggestVisible.value = false; return }
  suggestTimer = window.setTimeout(async () => {
    try {
      const r = await suggest({ q: q.value, alpha: alpha.value, size: 8 })
      suggestions.value = r.suggestions
      suggestVisible.value = true
    } catch { /* swallow */ }
  }, 180)
}

function pickSuggestion(text: string) {
  q.value = text
  suggestVisible.value = false
  runSearch()
}

let lastAlpha = alpha.value
function onAlphaChange(v: number) {
  trackTuning('alpha', lastAlpha, v)
  lastAlpha = v
  alpha.value = v
}
let lastBeta = beta.value
function onBetaChange(v: number) {
  trackTuning('beta', lastBeta, v)
  lastBeta = v
  beta.value = v
}
function onSourcesChange(next: Record<string, boolean>) {
  for (const k of Object.keys(next)) {
    if (next[k] !== sources.value[k]) trackSourceFilter(k, next[k])
  }
  sources.value = next
}

function jumpPage(delta: number) {
  const next = page.value + delta
  if (next < 0 || next >= pageCount.value) return
  page.value = next
  runSearch(false)
}

async function onClickResult(hit: Hit, rank: number) {
  trackClick(hit.doc_id, rank, q.value)
  if (isLoggedIn.value) {
    try { await click({ doc_id: hit.doc_id, query: q.value }) } catch { /* swallow */ }
  }
}
</script>

<template>
  <div class="container">
    <div class="search-area">
      <div class="placeholder mono">搜索角色 / 关键词 · 支持 "短语" · 通配 *? · source:fandom 限定</div>
      <div class="searchbox">
        <input
          type="search"
          v-model="q"
          placeholder="Luffy / 路飞 / Harry Potter ..."
          @input="onInput"
          @focus="onInput"
          @blur="onBlurDelay"
          @keydown.enter="runSearch()"
        />
        <SuggestDropdown
          :items="suggestions"
          :visible="suggestVisible"
          @pick="pickSuggestion"
        />
      </div>

      <TuningPanel
        :alpha="alpha"
        :beta="beta"
        :sources="sources"
        :rating="rating"
        :language="language"
        @update:alpha="onAlphaChange"
        @update:beta="onBetaChange"
        @update:sources="onSourcesChange"
        @update:rating="(v: string) => { rating = v; runSearch() }"
        @update:language="(v: string) => { language = v; runSearch() }"
      />
    </div>

    <hr class="divider" />

    <div v-if="loading" class="loading mono">载入中…</div>
    <div v-if="error" class="err">{{ error }}</div>

    <div v-if="result" class="result-area">
      <div class="result-meta mono">
        {{ result.total.toLocaleString() }} 条结果 · {{ result.took_ms }} ms · kind={{ result.kind }}
      </div>

      <div v-if="result.hits.length === 0" class="empty">
        没有匹配的档案。试试更宽松的关键词或调高 α 发散度。
      </div>

      <ResultEntry
        v-for="(h, i) in result.hits"
        :key="h.doc_id"
        :hit="h"
        :index="page * PAGE_SIZE + i + 1"
        :query="q"
        @click-result="onClickResult"
      />

      <div v-if="pageCount > 1" class="pager mono">
        <button class="ghost small" :disabled="page === 0" @click="jumpPage(-1)">← 上一页</button>
        <span>{{ page + 1 }} / {{ pageCount.toLocaleString() }}</span>
        <button class="ghost small" :disabled="page + 1 >= pageCount" @click="jumpPage(1)">下一页 →</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.search-area { margin-top: var(--sp-6); }
.placeholder {
  color: var(--ink-2);
  font-size: var(--text-sm);
  margin-bottom: var(--sp-3);
  text-align: center;
}
.searchbox {
  position: relative;
}
.searchbox input {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  padding: var(--sp-4) var(--sp-5);
}
.divider { margin: var(--sp-6) 0 var(--sp-4); }
.loading { color: var(--ink-2); padding: var(--sp-5) 0; text-align: center; }
.err {
  color: var(--err);
  padding: var(--sp-3);
  background: rgba(168, 74, 85, 0.05);
  border: 1px solid var(--err);
}
.result-meta {
  font-size: var(--text-sm);
  color: var(--ink-2);
  margin-bottom: var(--sp-2);
}
.empty {
  text-align: center;
  color: var(--ink-2);
  padding: var(--sp-8) 0;
  font-style: italic;
}
.pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--sp-5);
  padding: var(--sp-6) 0;
  font-size: var(--text-sm);
  color: var(--ink-2);
}
button.small { padding: 4px var(--sp-3); font-size: var(--text-sm); }
</style>
