<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter, RouterLink } from 'vue-router'
import { register } from '../lib/api'
import { setSession } from '../lib/auth'

const router = useRouter()

const step = ref<1 | 2>(1)
const email = ref('')
const password = ref('')
const error = ref('')

const SUGGESTED_INTERESTS = [
  'One Piece', 'Genshin Impact', 'Harry Potter', 'Naruto', 'Hetalia',
  'Touhou', 'Honkai: Star Rail', 'Marvel', 'Doctor Who',
]
const interests = ref<string[]>([])

const sources = ref<Record<string, number>>({ fandom: 0.6, wiki: 0.3, reddit: 0.1 })

const submitting = ref(false)

const canStep1 = computed(() => email.value.length > 3 && password.value.length >= 6)

function toggleInterest(s: string) {
  const i = interests.value.indexOf(s)
  if (i >= 0) interests.value.splice(i, 1)
  else interests.value.push(s)
}

function nextStep() {
  if (!canStep1.value) return
  step.value = 2
}

async function submit() {
  submitting.value = true
  error.value = ''
  try {
    const r = await register({
      email: email.value,
      password: password.value,
      interests: interests.value,
      preferred_sources: sources.value,
    })
    setSession(r.access_token, r.user_id)
    router.push('/search')
  } catch (e: any) {
    error.value = e?.detail || '注册失败'
    step.value = 1
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="wrap">
    <div class="step-marker mono">── 第{{ step }}步 / 二 ──</div>

    <section v-if="step === 1" class="card">
      <h2>建立档案</h2>
      <hr class="rule" />
      <form @submit.prevent="nextStep">
        <label>Email</label>
        <input v-model="email" type="email" required />
        <label>Password （≥6 字）</label>
        <input v-model="password" type="password" required minlength="6" />
        <p v-if="error" class="err">{{ error }}</p>
        <button :disabled="!canStep1" type="submit">下一步 →</button>
      </form>
      <p class="alt">
        已有账号 · <RouterLink to="/login">登录</RouterLink>
      </p>
    </section>

    <section v-else class="card">
      <h2>你常关注的作品</h2>
      <p class="hint">在喜欢的作品上盖章（多选，可跳过）</p>
      <div class="chips">
        <span
          v-for="s in SUGGESTED_INTERESTS"
          :key="s"
          class="chip"
          :class="{ active: interests.includes(s) }"
          @click="toggleInterest(s)"
        >{{ s }}</span>
      </div>

      <h3 class="sub">站点偏好</h3>
      <div v-for="(_, key) in sources" :key="key" class="src-row">
        <span class="src-name mono">{{ key }}</span>
        <input
          type="range"
          min="0"
          max="1"
          step="0.05"
          v-model.number="sources[key]"
        />
        <span class="src-val mono">{{ sources[key].toFixed(2) }}</span>
      </div>

      <div class="actions">
        <button class="ghost" @click="step = 1">← 返回</button>
        <button :disabled="submitting" @click="submit">
          {{ submitting ? '建立中…' : '完成' }}
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.wrap {
  max-width: 540px;
  margin: var(--sp-8) auto;
  padding: 0 var(--sp-4);
}
.step-marker {
  color: var(--ink-2);
  font-size: var(--text-sm);
  letter-spacing: 0.1em;
  text-align: center;
  margin-bottom: var(--sp-5);
}
.card {
  background: var(--paper-2);
  padding: var(--sp-6);
  box-shadow: var(--shadow-paper);
}
h2 {
  font-family: var(--font-display);
  font-size: var(--text-2xl);
}
.rule {
  border: none;
  border-top: 1px solid var(--rule);
  margin: var(--sp-3) 0 var(--sp-5);
}
.hint { color: var(--ink-2); font-size: var(--text-sm); margin: var(--sp-2) 0 var(--sp-4); }
label {
  display: block;
  margin-top: var(--sp-4);
  margin-bottom: var(--sp-2);
  font-size: var(--text-sm);
  color: var(--ink-2);
  font-family: var(--font-mono);
}
form button { margin-top: var(--sp-5); width: 100%; }
.chips { display: flex; flex-wrap: wrap; margin: 0 -4px; }
.sub {
  font-family: var(--font-display);
  font-size: var(--text-lg);
  margin: var(--sp-6) 0 var(--sp-3);
  border-bottom: 1px solid var(--rule);
  padding-bottom: var(--sp-2);
}
.src-row {
  display: grid;
  grid-template-columns: 80px 1fr 60px;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-2) 0;
}
.src-name { text-transform: uppercase; font-size: var(--text-sm); color: var(--ink-2); }
.src-val { text-align: right; color: var(--ink); }
input[type="range"] {
  width: 100%;
  accent-color: var(--ink-blue);
}
.actions {
  display: flex;
  justify-content: space-between;
  gap: var(--sp-3);
  margin-top: var(--sp-6);
}
.actions button { flex: 1; }
.alt {
  margin-top: var(--sp-5);
  font-size: var(--text-sm);
  color: var(--ink-2);
}
.err { color: var(--err); font-size: var(--text-sm); margin-top: var(--sp-3); }
</style>
