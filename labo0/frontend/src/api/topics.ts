/** Acces au backend : seules les URLs et les appels reseau vivent ici. */

import type { TopicInfo } from '../types'

export async function fetchTopics(): Promise<TopicInfo[]> {
  const res = await fetch('/api/topics')
  if (!res.ok) throw new Error(`GET /api/topics : HTTP ${res.status}`)
  const body = (await res.json()) as { topics: TopicInfo[] }
  return body.topics
}

/** URL du flux WebSocket d'un topic (passe par le proxy Vite en dev). */
export function wsUrl(topic: string): string {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${location.host}/ws/${topic}`
}
