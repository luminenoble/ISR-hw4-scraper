<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { computed } from 'vue'
import { snapshotUrl, search } from '../lib/api'
import { ref, onMounted } from 'vue'
import type { Hit } from '../lib/api'

const route = useRoute()
const router = useRouter()

const docId = computed(() => route.params.id as string)
const title = computed(() => route.query.title as string || '')
const source = computed(() => route.query.source as string || '')
const tag = computed(() => route.query.tag as string || '')
const url = computed(() => route.query.url as string || '')

const related = ref<Hit[]>([])
const loadingRel = ref(false)

onMounted(async () => {
  // 拉同 source 的相关条目：用 title 去搜，过滤 same source，去掉自己
  if (!title.value) return
  loadingRel.value = true
  try {
    const r = await search({ q: title.value, size: 10, source: source.value || undefined, alpha: 0.3 })
    related.value = r.hits.filter(h => h.doc_id !== docId.value).slice(0, 6)
  } finally {
    loadingRel.value = false
  }
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
        <div v-if="url"><dt>url</dt><dd class="url-cell">{{ url }}</dd></div>
      </dl>

      <p class="lede">
        档案条目快照与原始链接见右侧。完整正文请通过"网页快照"查看，避免直接转贴第三方内容。
      </p>
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
</style>
