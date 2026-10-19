import { useEffect, useState } from 'react'
import { wsUrl } from '../api/topics'
import { appendBatch, RECONNECT_DELAY_MS } from '../lib/stream'
import type { ConnectionStatus, SensorSeries, TopicRecord } from '../types'

const FLUSH_INTERVAL_MS = 500

interface StreamState {
  topic: string | null
  sensors: Record<string, SensorSeries>
  status: ConnectionStatus
}

const NO_SENSORS: Record<string, SensorSeries> = {}

const initialState = (topic: string | null): StreamState => ({ topic, sensors: NO_SENSORS, status: 'connecting' })

/**
 * Flux WebSocket d'un topic, regroupe par capteur. Messages integres par lots
 * (500 ms) : un re-rendu par lot, pas par message. Etat etiquete par topic :
 * un nouveau topic rend « connecting », jamais les donnees du precedent ; une
 * coupure reste « disconnected » pendant les tentatives (pas de clignotement).
 */
export function useTopicStream(topic: string | null) {
  const [state, setState] = useState<StreamState>(() => initialState(topic))

  useEffect(() => {
    if (!topic) return

    let ws: WebSocket | null = null
    let closed = false
    let reconnectTimer: number | undefined
    let pending: TopicRecord[] = []
    // Mise a jour de l'etat de CE topic (celui d'un autre topic repart de zero)
    const update = (fn: (s: StreamState) => StreamState) =>
      setState((prev) => fn(prev.topic === topic ? prev : initialState(topic)))

    const connect = () => {
      ws = new WebSocket(wsUrl(topic))
      ws.onopen = () => update((s) => ({ ...s, status: 'live' }))
      ws.onmessage = (e: MessageEvent<string>) => {
        if (closed) return
        try {
          pending.push(JSON.parse(e.data) as TopicRecord)
        } catch {
          // message illisible : ignore
        }
      }
      ws.onclose = () => {
        if (closed) return
        update((s) => ({ ...s, status: 'disconnected' }))
        reconnectTimer = window.setTimeout(connect, RECONNECT_DELAY_MS)
      }
    }
    connect()

    const flushTimer = window.setInterval(() => {
      if (pending.length === 0) return
      const batch = pending
      pending = []
      update((s) => {
        const sensors = appendBatch(s.sensors, batch)
        return sensors === s.sensors ? s : { ...s, sensors }
      })
    }, FLUSH_INTERVAL_MS)

    return () => {
      closed = true
      window.clearTimeout(reconnectTimer)
      window.clearInterval(flushTimer)
      ws?.close()
    }
  }, [topic])

  return state.topic === topic ? state : initialState(topic)
}
