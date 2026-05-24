<script setup lang="ts">
import { useRouter } from 'vue-router'
import type { Hit } from '../lib/api'
import { snapshotUrl } from '../lib/api'

const props = defineProps<{ hit: Hit; index: number; query: string }>()
const emit = defineEmits<{ (e: 'click-result', hit: Hit, rank: number): void }>()
const router = useRouter()

function goDetail() {
  emit('click-result', props.hit, props.index)
  router.push({
    path: `/doc/${props.hit.doc_id}`,
    query: {
      title: props.hit.title || '',
      source: props.hit.source || '',
      tag: props.hit.tag || '',
      url: props.hit.url || '',
    },
  })
}

function openSnapshot() {
  emit('click-result', props.hit, props.index)
  window.open(snapshotUrl(props.hit.doc_id), '_blank', 'noopener')
}
</script>

<template>
  <article class="entry">
    <div class="gutter">
      <div class="num mono">{{ String(index).padStart(3, '0') }}</div>
      <div class="bar"></div>
    </div>
    <div class="body">
      <div class="meta-top">
        <span v-if="hit.source" class="badge" :data-source="hit.source">{{ hit.source }}</span>
        <span v-if="hit.tag" class="tag" :data-tag="hit.tag">{{ hit.tag }}</span>
      </div>
      <h3 class="title">{{ hit.title || hit.doc_id }}</h3>
      <hr class="dashrule" />
      <p v-if="hit.snippet" class="snippet" v-html="hit.snippet"></p>
      <p v-else class="snippet placeholder">（无摘要）</p>
      <div class="meta-bot mono">
        <span>score {{ hit.score.toFixed(4) }}</span>
        <span v-if="hit.url" class="url">· {{ hit.url.slice(0, 60) }}{{ hit.url.length > 60 ? '…' : '' }}</span>
        <span class="actions">
          <button class="ghost small" @click="openSnapshot">⎘ 快照</button>
          <button class="small" @click="goDetail">→ 详情</button>
        </span>
      </div>
    </div>
  </article>
</template>

<style scoped>
.entry {
  display: grid;
  grid-template-columns: 56px 1fr;
  padding: var(--sp-5) 0;
  border-bottom: 1px solid var(--rule);
}
.gutter {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-right: var(--sp-3);
}
.num {
  font-size: var(--text-sm);
  color: var(--ink-2);
  font-weight: 500;
}
.bar {
  width: 2px;
  flex: 1;
  background: var(--rule);
  margin-top: var(--sp-2);
}
.body { min-width: 0; }
.meta-top {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-bottom: var(--sp-2);
}
.title {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  font-weight: 600;
  margin: 0;
  line-height: 1.25;
}
.dashrule {
  border: none;
  border-top: 1px dashed var(--rule);
  margin: var(--sp-2) 0 var(--sp-3);
}
.snippet {
  font-family: var(--font-body);
  font-size: var(--text-base);
  line-height: 1.55;
  color: var(--ink);
  margin: 0 0 var(--sp-3);
}
.snippet.placeholder { color: var(--ink-2); font-style: italic; }
.meta-bot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-3);
  font-size: var(--text-xs);
  color: var(--ink-2);
}
.url { word-break: break-all; }
.actions {
  margin-left: auto;
  display: flex;
  gap: var(--sp-2);
}
.actions button { padding: 3px 10px; font-size: var(--text-xs); font-family: var(--font-mono); }
</style>
