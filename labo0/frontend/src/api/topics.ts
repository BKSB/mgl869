/** Acces au backend : seules les URLs et les appels reseau vivent ici. */

import type { AlertsSnapshot, HealthInfo, TopicInfo } from '../types'

/** Content-type verifie : sans proxy, try_files servirait index.html en 200. */
async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(path, { signal, headers: { Accept: 'application/json' } })
  const ct = res.headers.get('content-type') ?? ''
  if (!res.ok || !ct.includes('application/json')) {
    throw new Error(`GET ${path} : HTTP ${res.status} (${ct || 'sans type'})`)
  }
  return (await res.json()) as T
}

export async function fetchTopics(): Promise<TopicInfo[]> {
  const body = await getJson<{ topics: TopicInfo[] }>('/api/topics')
  return body.topics
}

export function fetchHealth(signal?: AbortSignal): Promise<HealthInfo> {
  return getJson('/health', signal)
}

export function fetchAlerts(signal?: AbortSignal): Promise<AlertsSnapshot> {
  return getJson('/api/alerts', signal)
}

/** /ws/<topic> ou /ws/alerts sur l'hote courant (proxy Vite en dev). */
export function wsUrl(stream: string): string {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${location.host}/ws/${stream}`
}
