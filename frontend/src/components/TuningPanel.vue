<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  alpha: number
  beta: number
  sources: Record<string, boolean>
}>()

const emit = defineEmits<{
  (e: 'update:alpha', v: number): void
  (e: 'update:beta', v: number): void
  (e: 'update:sources', v: Record<string, boolean>): void
}>()

const open = ref(false)

const SOURCES = ['fandom', 'wiki', 'reddit', 'document'] as const

function onAlpha(e: Event) {
  emit('update:alpha', Number((e.target as HTMLInputElement).value))
}
function onBeta(e: Event) {
  emit('update:beta', Number((e.target as HTMLInputElement).value))
}
function toggleSrc(s: string) {
  emit('update:sources', { ...props.sources, [s]: !props.sources[s] })
}

// 同步外部默认值变化时不强制展开
watch(() => [props.alpha, props.beta], () => {}, { immediate: true })
</script>

<template>
  <div class="panel">
    <button class="toggle" type="button" @click="open = !open">
      <span class="arrow">{{ open ? '▾' : '▸' }}</span> {{ open ? '收起调节' : '展开调节' }}
      <span class="snapshot mono">α {{ alpha.toFixed(2) }} · β {{ beta.toFixed(2) }}</span>
    </button>
    <div v-if="open" class="body">
      <div class="row">
        <div class="row-head">
          <span class="lbl mono">α</span>
          <span class="hint">发散度</span>
          <span class="val mono">{{ alpha.toFixed(2) }}</span>
        </div>
        <div class="slider-line">
          <span class="end-left mono">📜 官方典籍</span>
          <input
            type="range"
            min="0" max="1" step="0.05"
            :value="alpha"
            class="slider alpha"
            @input="onAlpha"
          />
          <span class="end-right mono">✒ 民间二创</span>
        </div>
      </div>

      <div class="row">
        <div class="row-head">
          <span class="lbl mono">β</span>
          <span class="hint">个性化</span>
          <span class="val mono">{{ beta.toFixed(2) }}</span>
        </div>
        <div class="slider-line">
          <span class="end-left mono">保守</span>
          <input
            type="range"
            min="0" max="2" step="0.05"
            :value="beta"
            class="slider"
            @input="onBeta"
          />
          <span class="end-right mono">激进</span>
        </div>
      </div>

      <div class="row">
        <div class="row-head">
          <span class="hint">来源过滤</span>
        </div>
        <div class="checks">
          <label v-for="s in SOURCES" :key="s">
            <input type="checkbox" :checked="sources[s]" @change="toggleSrc(s)" />
            <span class="mono">{{ s }}</span>
          </label>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.panel {
  border: var(--bd);
  background: var(--paper);
  margin: var(--sp-4) 0;
}
.toggle {
  width: 100%;
  text-align: left;
  background: transparent;
  color: var(--ink);
  padding: var(--sp-3) var(--sp-4);
  border-radius: 0;
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  font-family: var(--font-body);
}
.toggle:hover { background: var(--paper-2); }
.toggle .arrow { color: var(--ink-blue); width: 14px; }
.toggle .snapshot {
  margin-left: auto;
  font-size: var(--text-sm);
  color: var(--ink-2);
}
.body {
  padding: var(--sp-4) var(--sp-5) var(--sp-5);
  border-top: 1px dashed var(--rule);
}
.row { padding: var(--sp-3) 0; }
.row + .row { border-top: 1px dotted var(--rule); }
.row-head {
  display: flex;
  align-items: baseline;
  gap: var(--sp-3);
  margin-bottom: var(--sp-2);
}
.lbl { color: var(--ink-blue); font-weight: 600; }
.hint { color: var(--ink-2); font-size: var(--text-sm); }
.val { margin-left: auto; color: var(--ink); }
.slider-line {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: var(--sp-3);
}
.end-left, .end-right { font-size: var(--text-xs); color: var(--ink-2); }
.slider {
  width: 100%;
  accent-color: var(--ink-blue);
}
.slider.alpha {
  /* 让 alpha 轨道呈现蓝→粉渐变（仅装饰背景） */
  background: linear-gradient(to right, var(--ink-blue-soft), var(--stamp-rose-soft));
  border-radius: 0;
  height: 4px;
  -webkit-appearance: none;
  appearance: none;
}
.slider.alpha::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 14px; height: 14px;
  background: var(--ink);
  border-radius: 0;
  cursor: pointer;
}
.slider.alpha::-moz-range-thumb {
  width: 14px; height: 14px;
  background: var(--ink);
  border-radius: 0;
  border: none;
  cursor: pointer;
}
.checks {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-4);
}
.checks label {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  cursor: pointer;
  font-size: var(--text-sm);
}
.checks input[type="checkbox"] {
  accent-color: var(--ink-blue);
  width: 16px;
  height: 16px;
}
</style>
