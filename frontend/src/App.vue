<script setup lang="ts">
import { RouterLink, RouterView, useRouter } from 'vue-router'
import { isLoggedIn, clearSession, uid } from './lib/auth'

const router = useRouter()

function logout() {
  clearSession()
  router.push('/login')
}
</script>

<template>
  <header class="masthead">
    <div class="masthead__inner">
      <RouterLink to="/search" class="brand">
        <span class="brand__mark">✒</span>
        <span class="brand__name">ISR.</span>
      </RouterLink>
      <nav class="nav">
        <RouterLink to="/search">搜索</RouterLink>
        <RouterLink v-if="isLoggedIn" to="/me">档案</RouterLink>
        <RouterLink v-if="isLoggedIn" to="/log">日志</RouterLink>
        <template v-if="!isLoggedIn">
          <RouterLink to="/login">登录</RouterLink>
        </template>
        <template v-else>
          <span class="uid mono">{{ uid }}</span>
          <button class="ghost small" @click="logout">注销</button>
        </template>
      </nav>
    </div>
  </header>
  <main>
    <RouterView />
  </main>
  <footer class="footer">
    <div class="container">
      <span class="mono">── ISR / 2026 · 角色档案馆 · ISR-Course Project ──</span>
    </div>
  </footer>
</template>

<style scoped>
.masthead {
  border-bottom: var(--bd);
  background: var(--paper);
  position: sticky;
  top: 0;
  z-index: 50;
}
.masthead__inner {
  max-width: var(--maxw-page);
  margin: 0 auto;
  padding: var(--sp-3) var(--sp-4);
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-4);
}
.brand {
  display: flex;
  align-items: baseline;
  gap: var(--sp-2);
  font-family: var(--font-display);
  color: var(--ink);
  border-bottom: none;
}
.brand__mark { color: var(--stamp-rose); font-size: 1.2em; }
.brand__name { font-weight: 800; letter-spacing: 0.02em; }
.nav {
  display: flex;
  align-items: baseline;
  gap: var(--sp-5);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
}
.nav a {
  color: var(--ink-2);
  border-bottom: none;
}
.nav a.router-link-active { color: var(--ink-blue); border-bottom: 1.5px solid var(--ink-blue); }
.uid { color: var(--ink-2); font-size: var(--text-xs); }
button.small { padding: 4px var(--sp-3); font-size: var(--text-sm); }
.footer {
  margin-top: var(--sp-10);
  padding: var(--sp-5) 0;
  border-top: var(--bd);
  color: var(--ink-2);
  text-align: center;
  font-size: var(--text-sm);
}
</style>
