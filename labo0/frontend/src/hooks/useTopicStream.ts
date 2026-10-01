import { useEffect, useRef, useState } from 'react'
import { wsUrl } from '../api/topics'
import type { ConnectionStatus, SensorSeries, TopicRecord, SensorValue } from '../types'

// Assez pour l'historique le plus profond du backend (3 h a 6 s = 1800
// points pour le niveau sonore, cf. backend/config/topics.yaml)
const MAX_POINTS = 2000
const FLUSH_INTERVAL_MS = 500
const RECONNECT_DELAY_MS = 3000

/**
 * S'abonne au flux WebSocket d'un topic et regroupe les messages par capteur
 * (node_id). Les messages sont tamponnes puis integres a l'etat 2x par
 * seconde : le rejeu d'historique et les topics rapides ne declenchent pas
 * un re-rendu par message.
 */
export function useTopicStream(topic: string | null) {
  const [sensors, setSensors] = useState<Record<string, SensorSeries>>({})
  const [status, setStatus] = useState<ConnectionStatus>('disconnected')
  const pending = useRef<TopicRecord[]>([])

  useEffect(() => {
    if (!topic) return
    setSensors({})
    pending.current = []

    let ws: WebSocket | null = null
    let closed = false
    let reconnectTimer: number | undefined

    const connect = () => {
      setStatus('connecting')
      ws = new WebSocket(wsUrl(topic))
      ws.onopen = () => setStatus('live')
      ws.onmessage = (e) => pending.current.push(JSON.parse(e.data))
      ws.onclose = () => {
        if (!closed) {
          setStatus('disconnected')
          reconnectTimer = window.setTimeout(connect, RECONNECT_DELAY_MS)
        }
      }
    }
    connect()

    const flushTimer = window.setInterval(() => {
      if (pending.current.length === 0) return
      const batch = pending.current
      pending.current = []
      setSensors((prev) => {
        const next = { ...prev }
        for (const rec of batch) {
          const value = rec.value
          if (value === null || typeof value !== 'object') continue
          const sensor = value as SensorValue
          const id = sensor.node_id ?? rec.key ?? 'inconnu'
          if (typeof sensor.value !== 'number') continue
          const series = next[id] ?? { points: [], last: sensor }
          next[id] = {
            last: sensor,
            points: [...series.points, { t: rec.timestamp_ms, v: sensor.value }]
              .slice(-MAX_POINTS),
          }
        }
        return next
      })
    }, FLUSH_INTERVAL_MS)

    return () => {
      closed = true
      window.clearTimeout(reconnectTimer)
      window.clearInterval(flushTimer)
      ws?.close()
    }
  }, [topic])

  return { sensors, status }
}
