import { createRouter, createWebHistory } from 'vue-router'
import { isLoggedIn } from './lib/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/search' },
    { path: '/login', component: () => import('./pages/Login.vue') },
    { path: '/register', component: () => import('./pages/Register.vue') },
    { path: '/search', component: () => import('./pages/Search.vue') },
    { path: '/doc/:id', component: () => import('./pages/Detail.vue'), props: true },
    { path: '/me', component: () => import('./pages/Profile.vue'), meta: { authed: true } },
    { path: '/log', component: () => import('./pages/Log.vue'), meta: { authed: true } },
  ],
})

router.beforeEach((to) => {
  if (to.meta.authed && !isLoggedIn.value) {
    return { path: '/login', query: { next: to.fullPath } }
  }
})

export default router
