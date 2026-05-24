/* 鉴权状态：JWT 存 localStorage，全局 reactive ref 暴露登录态。 */

import { ref, computed } from 'vue'

const KEY = 'isr_jwt'
const KEY_UID = 'isr_uid'

const _token = ref<string | null>(localStorage.getItem(KEY))
const _uid = ref<string | null>(localStorage.getItem(KEY_UID))

export const token = computed(() => _token.value)
export const uid = computed(() => _uid.value)
export const isLoggedIn = computed(() => !!_token.value)

export function getToken(): string | null {
  return _token.value
}

export function setSession(t: string, u: string) {
  _token.value = t
  _uid.value = u
  localStorage.setItem(KEY, t)
  localStorage.setItem(KEY_UID, u)
}

export function clearSession() {
  _token.value = null
  _uid.value = null
  localStorage.removeItem(KEY)
  localStorage.removeItem(KEY_UID)
}
