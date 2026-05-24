<script setup lang="ts">
import type { Suggestion } from '../lib/api'

defineProps<{
  items: Suggestion[]
  visible: boolean
}>()

const emit = defineEmits<{
  (e: 'pick', text: string): void
}>()

function kindMark(k: string): string {
  if (k === 'history') return '▸'
  if (k === 'title') return '·'
  return '◇'
}
</script>

<template>
  <div v-if="visible && items.length" class="dropdown">
    <button
      v-for="(s, i) in items"
      :key="i"
      class="row"
      type="button"
      @mousedown.prevent="emit('pick', s.text)"
    >
      <span class="mark" :class="s.kind">{{ kindMark(s.kind) }}</span>
      <span class="kind mono">{{ s.kind }}</span>
      <span class="text">{{ s.text }}</span>
    </button>
  </div>
</template>

<style scoped>
.dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  margin-top: 4px;
  background: var(--paper);
  border: var(--bd);
  box-shadow: var(--shadow-paper);
  z-index: 30;
  max-height: 360px;
  overflow-y: auto;
}
.row {
  display: grid;
  grid-template-columns: 24px 80px 1fr;
  align-items: baseline;
  gap: var(--sp-2);
  width: 100%;
  padding: var(--sp-2) var(--sp-3);
  background: transparent;
  color: var(--ink);
  border: none;
  text-align: left;
  cursor: pointer;
  border-bottom: 1px dotted var(--rule);
  font-family: var(--font-body);
  font-size: var(--text-base);
}
.row:last-child { border-bottom: none; }
.row:hover, .row:focus { background: var(--paper-2); outline: none; }
.mark { text-align: center; color: var(--ink-blue); }
.mark.semantic { color: var(--stamp-rose); }
.mark.history { color: var(--ink-blue); }
.kind {
  font-size: var(--text-xs);
  color: var(--ink-2);
  text-transform: lowercase;
}
.text { color: var(--ink); }
</style>
