<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { me, patchMe } from '../lib/api'
import type { UserProfile } from '../lib/api'

const profile = ref<UserProfile | null>(null)
const saving = ref(false)
const error = ref('')
const newInterest = ref('')

onMounted(async () => {
  try { profile.value = await me() } catch (e: any) { error.value = e?.detail || '加载失败' }
})

async function save() {
  if (!profile.value) return
  saving.value = true
  try {
    profile.value = await patchMe({
      interests: profile.value.interests,
      preferred_sources: profile.value.preferred_sources,
      preferred_tag_weights: profile.value.preferred_tag_weights,
      default_alpha: profile.value.default_alpha,
      default_beta: profile.value.default_beta,
    })
  } catch (e: any) {
    error.value = e?.detail || '保存失败'
  } finally {
    saving.value = false
  }
}

function addInterest() {
  const s = newInterest.value.trim()
  if (!s || !profile.value) return
  if (!profile.value.interests.includes(s)) profile.value.interests.push(s)
  newInterest.value = ''
}

function removeInterest(s: string) {
  if (!profile.value) return
  profile.value.interests = profile.value.interests.filter(x => x !== s)
}

function ensurePref(key: 'preferred_sources' | 'preferred_tag_weights', k: string) {
  if (!profile.value) return
  if (!(k in profile.value[key])) profile.value[key][k] = 0.5
}
</script>

<template>
  <div class="container">
    <div v-if="!profile" class="loading mono">载入中…</div>
    <div v-else>
      <header class="top">
        <div class="avatar">◯</div>
        <div>
          <div class="uid mono">{{ profile.user_id }}</div>
          <div class="email">{{ profile.email }}</div>
          <div class="meta mono">注册于 {{ profile.created_at.slice(0, 10) }} · 已点击 {{ profile.click_count }} 次</div>
        </div>
      </header>

      <section>
        <h3 class="sec-title">兴趣作品</h3>
        <hr class="rule" />
        <div class="chips">
          <span v-for="s in profile.interests" :key="s" class="chip active">
            {{ s }}
            <button class="x" @click="removeInterest(s)">×</button>
          </span>
        </div>
        <div class="add-int">
          <input v-model="newInterest" placeholder="新增…" @keydown.enter="addInterest" />
          <button class="ghost small" @click="addInterest">+ 添加</button>
        </div>
      </section>

      <section>
        <h3 class="sec-title">站点偏好 <span class="hint">(会被点击行为持续调整)</span></h3>
        <hr class="rule" />
        <div v-for="k in ['fandom','wiki','reddit','document']" :key="k" class="bar-row" @mouseenter="ensurePref('preferred_sources', k)">
          <span class="bar-name mono">{{ k }}</span>
          <div class="bar"><div class="bar-fill" :style="{ width: ((profile.preferred_sources[k] || 0) * 100) + '%' }"></div></div>
          <input
            type="range" min="0" max="1" step="0.05"
            :value="profile.preferred_sources[k] || 0"
            @input="(e) => profile && (profile.preferred_sources[k] = Number((e.target as HTMLInputElement).value))"
          />
          <span class="bar-val mono">{{ (profile.preferred_sources[k] || 0).toFixed(2) }}</span>
        </div>
      </section>

      <section>
        <h3 class="sec-title">标签偏好</h3>
        <hr class="rule" />
        <div v-for="k in ['canon','fanon','meta','crossover']" :key="k" class="bar-row" @mouseenter="ensurePref('preferred_tag_weights', k)">
          <span class="bar-name mono">{{ k }}</span>
          <div class="bar"><div class="bar-fill" :style="{ width: ((profile.preferred_tag_weights[k] || 0) * 100) + '%' }"></div></div>
          <input
            type="range" min="0" max="1" step="0.05"
            :value="profile.preferred_tag_weights[k] || 0"
            @input="(e) => profile && (profile.preferred_tag_weights[k] = Number((e.target as HTMLInputElement).value))"
          />
          <span class="bar-val mono">{{ (profile.preferred_tag_weights[k] || 0).toFixed(2) }}</span>
        </div>
      </section>

      <section>
        <h3 class="sec-title">默认调节</h3>
        <hr class="rule" />
        <div class="bar-row">
          <span class="bar-name mono">α</span>
          <span class="hint">新查询的初始发散度</span>
          <input type="range" min="0" max="1" step="0.05" v-model.number="profile.default_alpha" />
          <span class="bar-val mono">{{ profile.default_alpha.toFixed(2) }}</span>
        </div>
        <div class="bar-row">
          <span class="bar-name mono">β</span>
          <span class="hint">新查询的初始个性化</span>
          <input type="range" min="0" max="2" step="0.05" v-model.number="profile.default_beta" />
          <span class="bar-val mono">{{ profile.default_beta.toFixed(2) }}</span>
        </div>
      </section>

      <div class="actions">
        <button :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
        <p v-if="error" class="err">{{ error }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.loading { color: var(--ink-2); padding: var(--sp-8) 0; text-align: center; }
.top {
  display: flex;
  align-items: center;
  gap: var(--sp-5);
  padding: var(--sp-5) 0;
  border-bottom: var(--bd);
}
.avatar {
  width: 64px; height: 64px;
  border: 1.5px solid var(--ink);
  border-radius: var(--r-round);
  display: flex; align-items: center; justify-content: center;
  font-size: var(--text-2xl);
  color: var(--ink-blue);
}
.uid { color: var(--ink-2); font-size: var(--text-xs); }
.email { font-family: var(--font-display); font-size: var(--text-xl); margin: 2px 0; }
.meta { color: var(--ink-2); font-size: var(--text-xs); }
section { margin-top: var(--sp-6); }
.sec-title {
  font-family: var(--font-display);
  font-size: var(--text-xl);
}
.hint { font-family: var(--font-body); color: var(--ink-2); font-size: var(--text-sm); font-weight: 400; }
.rule { border: none; border-top: 1px solid var(--rule); margin: var(--sp-2) 0 var(--sp-4); }
.chips { display: flex; flex-wrap: wrap; }
.chip .x {
  background: transparent; border: none; color: var(--ink-blue); cursor: pointer;
  padding: 0 0 0 var(--sp-2); font-family: var(--font-mono);
}
.add-int {
  display: flex; gap: var(--sp-2); margin-top: var(--sp-3);
}
.add-int input { flex: 1; }
.bar-row {
  display: grid;
  grid-template-columns: 100px 1fr 200px 50px;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-2) 0;
}
.bar-name { color: var(--ink-2); text-transform: uppercase; }
.bar {
  height: 8px;
  background: var(--paper-2);
  border: 1px solid var(--rule);
}
.bar-fill {
  height: 100%;
  background: var(--ink-blue);
  transition: width 0.15s ease;
}
.bar-val { text-align: right; }
input[type="range"] { accent-color: var(--ink-blue); }
.actions { margin-top: var(--sp-8); padding-top: var(--sp-5); border-top: var(--bd); }
.err { color: var(--err); margin-top: var(--sp-3); }
</style>
