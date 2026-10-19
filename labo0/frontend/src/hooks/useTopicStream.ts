import { useEffect, useRef, useState } from 'react'
import { wsUrl } from '../api/topics'
import { RECONNECT_DELAY_MS } from '../lib/stream'
import type { ConnectionStatus, SensorSeries, TopicRecord, SensorValue } from '../types'

// Assez pour l'historique le plus profond du backend (3 h a 6 s = 1800
// points pour le niveau sonore, cf. backend/config/topics.yaml)
const MAX_POINTS = 2000
const FLUSH_INTERVAL_MS = 500

interface StreamState {
  /** Topic auquel appartiennent ces donnees. */
  topic: string | null
  sensors: Record<string, SensorSeries>
  status: ConnectionStatus
}

const NO_SENSORS: Record<string, SensorSeries> = {}

const initialState = (topic: string | null): StreamState => ({ topic, sensors: NO_SENSORS, status: 'connecting' })

/**
 * S'abonne au flux WebSocket d'un topic et regroupe les messages par capteur
 * (sensor_id fourni par le backend : la meme identite que les alertes). Les
 * messages sont tamponnes puis integres a l'etat 2x par seconde : le rejeu
 * d'historique et les topics rapides ne declenchent pas un re-rendu par
 * message.
 *
 * L'etat est etiquete par topic : des le premier rendu d'un nouveau topic
 * (avant l'effet), le hook rend « connecting » sans capteur, jamais les
 * donnees ni l'etat du topic precedent (ni le « disconnected » d'un flux pas
 * encore ouvert). Une coupure reste « disconnected » pendant les tentatives
 * de reconnexion, jusqu'au retour du flux : l'interface n'alterne pas entre
 * coupure et connexion a chaque tentative.
 */
export function useTopicStream(topic: string | null) {
  const [state, setState] = useState<StreamState>(() => initialState(topic))
  const pending = useRef<TopicRecord[]>([])

  useEffect(() => {
    if (!topic) return
    pending.current = []

    let ws: WebSocket | null = null
    let closed = false
    let reconnectTimer: number | undefined
    // Mise a jour de l'etat de CE topic (celui d'un autre topic repart de zero)
    const update = (fn: (s: StreamState) => StreamState) =>
      setState((prev) => fn(prev.topic === topic ? prev : initialState(topic)))

    const connect = () => {
      ws = new WebSocket(wsUrl(topic))
      ws.onopen = () => update((s) => ({ ...s, status: 'live' }))
      ws.onmessage = (e: MessageEvent<string>) => {
        if (closed) return
        try {
          pending.current.push(JSON.parse(e.data) as TopicRecord)
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
      if (pending.current.length === 0) return
      const batch = pending.current
      pending.current = []
      update((s) => {
        const next = { ...s.sensors }
        for (const rec of batch) {
          const value = rec.value
          if (value === null || typeof value !== 'object') continue
          const sensor = value as SensorValue
          if (typeof sensor.value !== 'number') continue
          const id = rec.sensor_id
          const series = next[id] ?? { points: [], last: sensor }
          next[id] = {
            last: sensor,
            points: [...series.points, { t: rec.timestamp_ms, v: sensor.value }]
              .slice(-MAX_POINTS),
          }
        }
        return { ...s, sensors: next }
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
