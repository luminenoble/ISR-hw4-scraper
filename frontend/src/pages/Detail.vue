<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { computed, ref, onMounted, watch } from 'vue'
import { snapshotUrl, search, getDoc } from '../lib/api'
import type { Hit, DocDetail } from '../lib/api'

const route = useRoute()
const router = useRouter()

const docId = computed(() => route.params.id as string)
// 列表带来的元数据作为占位；详情拉到后以 detail 为准
const detail = ref<DocDetail | null>(null)
const loadingDoc = ref(false)
const docError = ref<string | null>(null)

const title = computed(() => detail.value?.title || (route.query.title as string) || '')
const source = computed(() => detail.value?.source || (route.query.source as string) || '')
const tag = computed(() => detail.value?.tag || (route.query.tag as string) || '')
const url = computed(() => detail.value?.url || (route.query.url as string) || '')

const related = ref<Hit[]>([])
const loadingRel = ref(false)

async function loadDoc() {
  if (!docId.value) return
  loadingDoc.value = true
  docError.value = null
  try {
    detail.value = await getDoc(docId.value, 8000)
  } catch (e: unknown) {
    detail.value = null
    docError.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loadingDoc.value = false
  }
}

async function loadRelated() {
  const seed = title.value
  if (!seed) return
  loadingRel.value = true
  try {
    const r = await search({ q: seed, size: 10, source: source.value || undefined, alpha: 0.3 })
    related.value = r.hits.filter(h => h.doc_id !== docId.value).slice(0, 6)
  } finally {
    loadingRel.value = false
  }
}

onMounted(async () => {
  await loadDoc()
  await loadRelated()
})

watch(docId, async () => {
  await loadDoc()
  await loadRelated()
})

const infoboxEntries = computed(() => {
  const ib = detail.value?.infobox || {}
  return Object.entries(ib).filter(([_, v]) => v != null && String(v).trim() !== '').slice(0, 12)
})

function openSnapshot() {
  window.open(snapshotUrl(docId.value), '_blank', 'noopener')
}

function openOriginal() {
  if (url.value) window.open(url.value, '_blank', 'noopener')
}

function goRelated(h: Hit) {
  router.push({
    path: `/doc/${h.doc_id}`,
    query: { title: h.title || '', source: h.source || '', tag: h.tag || '', url: h.url || '' },
  })
}
</script>

<template>
  <div class="detail-wrap">
    <RouterLink to="/search" class="back mono">← 返回搜索</RouterLink>

    <article class="main">
      <div class="meta-top">
        <span v-if="source" class="badge" :data-source="source">{{ source }}</span>
        <span v-if="tag" class="tag" :data-tag="tag">{{ tag }}</span>
      </div>

      <h1 class="title">{{ title || docId }}</h1>
      <hr class="double" />

      <dl class="meta-list mono">
        <div><dt>doc_id</dt><dd>{{ docId }}</dd></div>
        <div v-if="source"><dt>source</dt><dd>{{ source }}</dd></div>
        <div v-if="detail?.character_name"><dt>character</dt><dd>{{ detail.character_name }}</dd></div>
        <div v-if="url"><dt>url</dt><dd class="url-cell">{{ url }}</dd></div>
        <div v-if="detail?.fetched_at"><dt>fetched</dt><dd>{{ detail.fetched_at }}</dd></div>
        <div v-if="detail?.pagerank != null"><dt>pagerank</dt><dd>{{ detail.pagerank.toExponential(3) }}</dd></div>
        <div v-if="detail?.obscurity != null"><dt>obscurity</dt><dd>{{ detail.obscurity.toFixed(3) }}</dd></div>
        <div v-if="detail?.popularity != null"><dt>popularity</dt><dd>{{ detail.popularity }}</dd></div>
      </dl>

      <div v-if="loadingDoc" class="hint mono">载入正文中…</div>
      <div v-else-if="docError" class="hint err">⚠ {{ docError }}</div>
      <template v-else>
        <section v-if="infoboxEntries.length" class="infobox">
          <h3>信息框</h3>
          <hr class="rule" />
          <dl class="ib mono">
            <div v-for="[k, v] in infoboxEntries" :key="k"><dt>{{ k }}</dt><dd>{{ v }}</dd></div>
          </dl>
        </section>

        <section v-if="detail?.body" class="body-section">
          <h3>正文</h3>
          <hr class="rule" />
          <div class="body-text">{{ detail.body }}</div>
        </section>
        <p v-else class="lede">本条目无正文存档，可通过"网页快照"查看原始页面。</p>
      </template>
    </article>

    <aside class="sidebar">
      <section class="panel">
        <h3>操作</h3>
        <hr class="rule" />
        <button class="action" @click="openSnapshot">⎘ 网页快照</button>
        <button v-if="url" class="action ghost" @click="openOriginal">↗ 原始链接</button>
      </section>

      <section class="panel">
        <h3>相关档案</h3>
        <hr class="rule" />
        <div v-if="loadingRel" class="hint mono">载入中…</div>
        <ul v-else-if="related.length" class="rel-list">
          <li v-for="h in related" :key="h.doc_id">
            <button class="rel-row" @click="goRelated(h)">
              <span class="badge small" :data-source="h.source">{{ h.source }}</span>
              <span class="rel-title">{{ h.title }}</span>
            </button>
          </li>
        </ul>
        <div v-else class="hint mono">无相关</div>
      </section>
    </aside>
  </div>
</template>

<style scoped>
.detail-wrap {
  max-width: var(--maxw-page);
  margin: var(--sp-5) auto;
  padding: 0 var(--sp-4);
  display: grid;
  grid-template-columns: minmax(0, 1fr) 260px;
  gap: var(--sp-8);
  align-items: start;
}
@media (max-width: 900px) {
  .detail-wrap { grid-template-columns: 1fr; }
}
.back {
  display: inline-block;
  color: var(--ink-blue);
  font-size: var(--text-sm);
  margin-bottom: var(--sp-4);
  grid-column: 1 / -1;
  border-bottom: none;
}
.meta-top { display: flex; gap: var(--sp-2); margin-bottom: var(--sp-3); }
.title {
  font-family: var(--font-display);
  font-size: var(--text-3xl);
  line-height: 1.15;
  font-weight: 800;
}
.double {
  border: none;
  border-top: 1.5px solid var(--ink);
  border-bottom: 1.5px solid var(--ink);
  height: 4px;
  margin: var(--sp-3) 0 var(--sp-5);
}
.meta-list { font-size: var(--text-sm); color: var(--ink-2); margin: 0 0 var(--sp-6); }
.meta-list > div { display: grid; grid-template-columns: 90px 1fr; padding: 2px 0; }
.meta-list dt { color: var(--ink-2); }
.meta-list dd { margin: 0; color: var(--ink); word-break: break-all; }
.url-cell { word-break: break-all; }
.lede { font-size: var(--text-base); color: var(--ink-2); line-height: 1.7; max-width: var(--maxw-reading); }
.sidebar { display: flex; flex-direction: column; gap: var(--sp-5); }
.panel {
  background: var(--paper-2);
  padding: var(--sp-4);
  border-left: 2px solid var(--ink-blue);
}
.panel h3 {
  font-family: var(--font-display);
  font-size: var(--text-lg);
  margin: 0;
}
.rule { border: none; border-top: 1px solid var(--rule); margin: var(--sp-2) 0 var(--sp-3); }
.action {
  display: block;
  width: 100%;
  text-align: left;
  margin-top: var(--sp-2);
  font-size: var(--text-sm);
}
.rel-list { list-style: none; padding: 0; margin: 0; }
.rel-row {
  display: flex;
  align-items: baseline;
  gap: var(--sp-2);
  width: 100%;
  background: transparent;
  color: var(--ink);
  border: none;
  padding: var(--sp-2) 0;
  border-bottom: 1px dotted var(--rule);
  text-align: left;
  cursor: pointer;
  font-family: var(--font-body);
  font-size: var(--text-sm);
}
.rel-row:hover { color: var(--ink-blue); }
.badge.small { font-size: 10px; padding: 1px 4px; }
.rel-title { flex: 1; word-break: break-word; }
.hint { color: var(--ink-2); font-size: var(--text-sm); }
.hint.err { color: var(--stamp-rose, #c2185b); }
.infobox { margin: var(--sp-4) 0 var(--sp-6); }
.infobox h3, .body-section h3 {
  font-family: var(--font-display);
  font-size: var(--text-lg);
  margin: 0;
}
.ib { font-size: var(--text-sm); color: var(--ink-2); margin-top: var(--sp-2); }
.ib > div { display: grid; grid-template-columns: 140px 1fr; padding: 2px 0; border-bottom: 1px dotted var(--rule); }
.ib dt { color: var(--ink-2); }
.ib dd { margin: 0; color: var(--ink); word-break: break-word; }
.body-section { margin-top: var(--sp-4); }
.body-text {
  font-family: var(--font-body, 'Crimson Pro'), Georgia, serif;
  font-size: var(--text-base);
  color: var(--ink);
  line-height: 1.75;
  margin-top: var(--sp-3);
  max-width: var(--maxw-reading);
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
