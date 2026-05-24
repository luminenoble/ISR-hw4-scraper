<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute, RouterLink } from 'vue-router'
import { login } from '../lib/api'
import { setSession } from '../lib/auth'

const router = useRouter()
const route = useRoute()

const email = ref('')
const password = ref('')
const submitting = ref(false)
const error = ref('')

async function submit() {
  if (!email.value || !password.value) return
  submitting.value = true
  error.value = ''
  try {
    const r = await login({ email: email.value, password: password.value })
    setSession(r.access_token, r.user_id)
    const next = (route.query.next as string) || '/search'
    router.push(next)
  } catch (e: any) {
    error.value = e?.detail || e?.message || '登录失败'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="split">
    <aside class="brandpanel">
      <div class="brand-mark">✒</div>
      <h1 class="brand-name">ISR.</h1>
      <hr />
      <p class="lede">
        角色档案馆<br />
        Character Dossier Archive
      </p>
      <p class="desc">面向同人创作者的<br />角色背景检索引擎。</p>
      <ul class="feats">
        <li>· 10 万 + 文档</li>
        <li>· Fandom / Wiki / Reddit</li>
        <li>· α 发散度可调</li>
      </ul>
      <p class="ver mono">──── ISR / 2026</p>
    </aside>

    <section class="form">
      <h2>登录</h2>
      <hr class="rule" />
      <form @submit.prevent="submit">
        <label>Email</label>
        <input v-model="email" type="email" autocomplete="email" required />
        <label>Password</label>
        <input v-model="password" type="password" autocomplete="current-password" required />
        <p v-if="error" class="err">{{ error }}</p>
        <button :disabled="submitting" type="submit">
          {{ submitting ? '验证中…' : '进入档案馆' }}
        </button>
      </form>
      <p class="alt">
        没有账号 · <RouterLink to="/register">注册</RouterLink>
      </p>
    </section>
  </div>
</template>

<style scoped>
.split {
  max-width: var(--maxw-page);
  margin: var(--sp-8) auto;
  padding: 0 var(--sp-4);
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-10);
  align-items: start;
}
@media (max-width: 768px) {
  .split { grid-template-columns: 1fr; gap: var(--sp-6); }
}
.brandpanel {
  padding: var(--sp-6) var(--sp-4);
}
.brand-mark {
  font-family: var(--font-display);
  color: var(--stamp-rose);
  font-size: 3rem;
  line-height: 1;
}
.brand-name {
  font-size: var(--text-4xl);
  font-weight: 800;
  font-family: var(--font-display);
  margin-top: var(--sp-2);
}
.brandpanel hr {
  width: 64px;
  border: none;
  border-top: 1.5px solid var(--ink);
  margin: var(--sp-4) 0 var(--sp-5);
}
.lede {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  line-height: 1.3;
  margin-bottom: var(--sp-4);
}
.desc { color: var(--ink-2); margin-bottom: var(--sp-6); }
.feats {
  list-style: none;
  padding: 0;
  margin: 0 0 var(--sp-8);
  color: var(--ink-2);
  font-size: var(--text-sm);
  line-height: 1.9;
}
.ver {
  color: var(--ink-2);
  font-size: var(--text-xs);
  letter-spacing: 0.1em;
}
.form {
  background: var(--paper-2);
  padding: var(--sp-6);
  box-shadow: var(--shadow-paper);
}
.form h2 {
  font-family: var(--font-display);
  font-size: var(--text-2xl);
}
.rule {
  border: none;
  border-top: 1px solid var(--rule);
  margin: var(--sp-3) 0 var(--sp-5);
}
label {
  display: block;
  margin-top: var(--sp-4);
  margin-bottom: var(--sp-2);
  font-size: var(--text-sm);
  color: var(--ink-2);
  font-family: var(--font-mono);
}
form button { margin-top: var(--sp-5); width: 100%; }
.err {
  color: var(--err);
  font-size: var(--text-sm);
  margin-top: var(--sp-3);
}
.alt {
  margin-top: var(--sp-5);
  font-size: var(--text-sm);
  color: var(--ink-2);
}
</style>
