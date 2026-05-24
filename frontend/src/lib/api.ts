/* API 客户端：所有调用走 /api/* 由 Vite proxy 转到 FastAPI。
   JWT 在 auth.ts 维护，这里只负责注入 Authorization header。 */

import { getToken } from './auth'

const BASE = '/api'

export interface Hit {
  doc_id: string
  score: number
  source?: string
  url?: string
  title?: string
  tag?: string
  snippet?: string
}

export interface SearchResponse {
  query: string
  kind: string
  total: number
  took_ms: number
  hits: Hit[]
  filters: Record<string, string>
}

export interface Suggestion {
  text: string
  score: number
  kind: 'history' | 'title' | 'semantic'
  doc_id?: string
}

export interface SuggestResponse {
  q: string
  alpha: number
  suggestions: Suggestion[]
}

export interface UserProfile {
  user_id: string
  email: string
  created_at: string
  interests: string[]
  preferred_sources: Record<string, number>
  preferred_tag_weights: Record<string, number>
  default_alpha: number
  default_beta: number
  click_count: number
}

export interface TokenResponse {
  access_token: string
  token_type: string
  user_id: string
}

export interface LogItem {
  user_id: string | null
  query: string
  kind: string
  filters: Record<string, string>
  alpha?: number
  beta?: number
  ts: string
  total: number
  result_ids: string[]
}

export interface ClickHistoryItem {
  doc_id: string
  ts: string
  dwell_ms: number | null
  query: string | null
}

class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(`API ${status}: ${detail}`)
  }
}

async function req<T>(
  path: string,
  init: RequestInit = {},
  expectEmpty = false,
): Promise<T> {
  const headers: Record<string, string> = {
    'content-type': 'application/json',
    ...((init.headers as Record<string, string>) || {}),
  }
  const tok = getToken()
  if (tok) headers.authorization = `Bearer ${tok}`
  const res = await fetch(BASE + path, { ...init, headers })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    let detail = text
    try {
      const j = JSON.parse(text)
      detail = j.detail || text
    } catch { /* keep text */ }
    throw new ApiError(res.status, detail || res.statusText)
  }
  if (expectEmpty) return undefined as T
  return (await res.json()) as T
}

/* ---------- auth ---------- */

export const register = (body: {
  email: string
  password: string
  interests?: string[]
  preferred_sources?: Record<string, number>
  preferred_tag_weights?: Record<string, number>
  default_alpha?: number
  default_beta?: number
}) => req<TokenResponse>('/auth/register', { method: 'POST', body: JSON.stringify(body) })

export const login = (body: { email: string; password: string }) =>
  req<TokenResponse>('/auth/login', { method: 'POST', body: JSON.stringify(body) })

export const me = () => req<UserProfile>('/auth/me')

export const patchMe = (patch: Partial<{
  interests: string[]
  preferred_sources: Record<string, number>
  preferred_tag_weights: Record<string, number>
  default_alpha: number
  default_beta: number
}>) => req<UserProfile>('/auth/me', { method: 'PATCH', body: JSON.stringify(patch) })

/* ---------- search ---------- */

export function search(params: {
  q: string
  size?: number
  from?: number
  source?: string
  alpha?: number
  beta?: number
  rating?: string
  language?: string
}) {
  const qs = new URLSearchParams()
  qs.set('q', params.q)
  if (params.size != null) qs.set('size', String(params.size))
  if (params.from != null) qs.set('from', String(params.from))
  if (params.source) qs.set('source', params.source)
  if (params.alpha != null) qs.set('alpha', String(params.alpha))
  if (params.beta != null) qs.set('beta', String(params.beta))
  if (params.rating) qs.set('rating', params.rating)
  if (params.language) qs.set('language', params.language)
  return req<SearchResponse>(`/search?${qs}`)
}

export function suggest(params: { q: string; alpha?: number; size?: number }) {
  const qs = new URLSearchParams({ q: params.q })
  if (params.alpha != null) qs.set('alpha', String(params.alpha))
  if (params.size != null) qs.set('size', String(params.size))
  return req<SuggestResponse>(`/suggest?${qs}`)
}

export const click = (body: { doc_id: string; query?: string; dwell_ms?: number }) =>
  req<UserProfile>('/feedback/click', { method: 'POST', body: JSON.stringify(body) })

export const event = (kind: string, payload: Record<string, unknown> = {}) =>
  req<void>('/feedback/event', { method: 'POST', body: JSON.stringify({ kind, payload }) }, true)

/* ---------- log ---------- */

export const myLogs = (limit = 50) =>
  req<{ count: number; items: LogItem[] }>(`/logs/me?limit=${limit}`)

export const myClicks = (limit = 50) =>
  req<{ count: number; items: ClickHistoryItem[] }>(`/logs/clicks/me?limit=${limit}`)

/* ---------- snapshot ---------- */

export const snapshotUrl = (doc_id: string) => `${BASE}/snapshot/${doc_id}`

/* ---------- document detail ---------- */

export interface DocDetail {
  doc_id: string
  source?: string
  url?: string
  title?: string
  tag?: string
  character_name?: string
  body?: string
  infobox: Record<string, unknown>
  popularity?: number
  pagerank?: number
  obscurity?: number
  fetched_at?: string
  has_snapshot: boolean
  has_embedding: boolean
}

export const getDoc = (doc_id: string, body_max = 8000) =>
  req<DocDetail>(`/doc/${encodeURIComponent(doc_id)}?body_max=${body_max}`)
