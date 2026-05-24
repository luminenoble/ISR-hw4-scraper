<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { myLogs, myClicks } from '../lib/api'
import type { LogItem, ClickHistoryItem } from '../lib/api'

const tab = ref<'search' | 'click'>('search')
const searchLogs = ref<LogItem[]>([])
const clickLogs = ref<ClickHistoryItem[]>([])
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    if (tab.value === 'search') {
      searchLogs.value = (await myLogs(100)).items
    } else {
      clickLogs.value = (await myClicks(100)).items
    }
  } catch (e: any) {
    error.value = e?.detail || '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)

function setTab(t: 'search' | 'click') {
  tab.value = t
  load()
}

function dateOf(iso: string): string { return iso.slice(0, 10) }
function timeOf(iso: string): string { return iso.slice(11, 19) }

const searchByDate = computed(() => {
  const m = new Map<string, LogItem[]>()
  for (const it of searchLogs.value) {
    const d = dateOf(it.ts)
    if (!m.has(d)) m.set(d, [])
    m.get(d)!.push(it)
  }
  return Array.from(m.entries())
})
const clickByDate = computed(() => {
  const m = new Map<string, ClickHistoryItem[]>()
  for (const it of clickLogs.value) {
    const d = dateOf(it.ts)
    if (!m.has(d)) m.set(d, [])
    m.get(d)!.push(it)
  }
  return Array.from(m.entries())
})
</script>

<template>
  <div class="container">
    <div class="tabs">
      <button :class="['tab', { active: tab === 'search' }]" @click="setTab('search')">搜索历史</button>
      <button :class="['tab', { active: tab === 'click' }]" @click="setTab('click')">点击历史</button>
    </div>

    <div v-if="loading" class="loading mono">载入中…</div>
    <div v-else-if="error" class="err">{{ error }}</div>

    <template v-else-if="tab === 'search'">
      <div v-for="[d, items] in searchByDate" :key="d">
        <div class="date-sep mono">── {{ d }} ──</div>
        <div v-for="(it, i) in items" :key="i" class="row">
          <div class="t mono">{{ timeOf(it.ts) }}</div>
          <div class="bar"></div>
          <div class="content">
            <div class="q">{{ it.query }}</div>
            <div class="meta mono">
              {{ it.total.toLocaleString() }} hits · {{ (it.alpha ?? 0).toFixed(2) }}α
              <span v-if="it.beta !== undefined">· {{ it.beta.toFixed(2) }}β</span>
              · {{ it.kind }}
            </div>
          </div>
        </div>
      </div>
      <div v-if="!searchLogs.length" class="empty">还没有搜索记录</div>
    </template>

    <template v-else>
      <div v-for="[d, items] in clickByDate" :key="d">
        <div class="date-sep mono">── {{ d }} ──</div>
        <div v-for="(it, i) in items" :key="i" class="row">
          <div class="t mono">{{ timeOf(it.ts) }}</div>
          <div class="bar"></div>
          <div class="content">
            <RouterLink :to="`/doc/${it.doc_id}`" class="q">{{ it.doc_id }}</RouterLink>
            <div class="meta mono">
              <span v-if="it.query">from "{{ it.query }}"</span>
              <span v-if="it.dwell_ms != null"> · 停留 {{ (it.dwell_ms / 1000).toFixed(1) }}s</span>
            </div>
          </div>
        </div>
      </div>
      <div v-if="!clickLogs.length" class="empty">还没有点击记录</div>
    </template>
  </div>
</template>

<style scoped>
.tabs {
  display: flex;
  gap: var(--sp-3);
  margin: var(--sp-5) 0;
  border-bottom: var(--bd);
}
.tab {
  background: transparent;
  color: var(--ink-2);
  border-radius: 0;
  padding: var(--sp-3) var(--sp-4);
  border-bottom: 2px solid transparent;
}
.tab.active { color: var(--ink-blue); border-bottom-color: var(--ink-blue); }
.tab:hover { background: var(--paper-2); }
.date-sep {
  text-align: center;
  color: var(--ink-2);
  margin: var(--sp-5) 0 var(--sp-3);
  letter-spacing: 0.1em;
}
.row {
  display: grid;
  grid-template-columns: 80px 16px 1fr;
  gap: var(--sp-3);
  padding: var(--sp-3) 0;
  border-bottom: 1px dotted var(--rule);
}
.t { color: var(--ink-2); font-size: var(--text-sm); padding-top: 2px; }
.bar {
  border-left: 1px solid var(--rule);
  margin-left: 7px;
}
.q { font-family: var(--font-display); font-size: var(--text-lg); color: var(--ink); }
.q[href]:hover { color: var(--ink-blue); }
.meta { font-size: var(--text-xs); color: var(--ink-2); margin-top: 2px; }
.empty {
  color: var(--ink-2);
  text-align: center;
  padding: var(--sp-8) 0;
  font-style: italic;
}
.loading { color: var(--ink-2); padding: var(--sp-8) 0; text-align: center; }
.err { color: var(--err); padding: var(--sp-4); }
</style>
