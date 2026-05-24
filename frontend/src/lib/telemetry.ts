/* 5 个指标的埋点。统一异步发到 /feedback/event 不阻塞 UI。
   sendBeacon 失败时降级到 fetch。 */

import { event } from './api'

function send(kind: string, payload: Record<string, unknown>) {
  // 火烧后忽略，避免影响主流程
  event(kind, payload).catch(() => { /* swallow */ })
}

export function trackLatency(query: string, took_ms: number, total: number) {
  send('search.latency', { query, took_ms, total })
}

export function trackEmpty(query: string) {
  send('search.empty', { query })
}

export function trackClick(doc_id: string, rank: number, query: string) {
  send('result.click', { doc_id, rank, query, rr: 1 / Math.max(1, rank) })
}

export function trackTuning(kind: 'alpha' | 'beta', from: number, to: number) {
  send(`tuning.${kind}`, { from, to })
}

export function trackSourceFilter(source: string, on: boolean) {
  send('filter.source', { source, on })
}
