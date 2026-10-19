/** Flux WebSocket (topics, alertes) : logique et textes partages par les hooks
 * et l'interface. */

import { fmtDuration } from './format'
import type { ConnectionStatus, SensorPoint, SensorSeries, SensorValue, TopicRecord } from '../types'

/** Par capteur : couvre le plus long historique du backend (niveau sonore,
 * 3 h a 6 s = 1800 points, cf. backend/config/topics.yaml). */
export const MAX_POINTS = 2000

/** Lot integre par sensor_id, dans l'ordre d'arrivee : une copie par capteur et
 * par lot (rejeu complet compris) ; lot sans point numerique : meme reference. */
export function appendBatch(sensors: Record<string, SensorSeries>, batch: TopicRecord[]): Record<string, SensorSeries> {
  const added: Record<string, { points: SensorPoint[]; last: SensorValue }> = {}
  for (const rec of batch) {
    const value = rec.value
    if (value === null || typeof value !== 'object' || typeof value.value !== 'number') continue
    const entry = (added[rec.sensor_id] ??= { points: [], last: value })
    entry.points.push({ t: rec.timestamp_ms, v: value.value })
    entry.last = value
  }
  const ids = Object.keys(added)
  if (ids.length === 0) return sensors
  const next = { ...sensors }
  for (const id of ids) {
    const { points, last } = added[id]
    next[id] = { last, points: [...(sensors[id]?.points ?? []), ...points].slice(-MAX_POINTS) }
  }
  return next
}

export const RECONNECT_DELAY_MS = 3000

/** « reconnexion toutes les 3 s » : reste vrai pendant toute la coupure. */
export const RECONNECT_TEXT = `reconnexion toutes les ${fmtDuration(RECONNECT_DELAY_MS)}`

/** Pourquoi le topic affiche n'a encore aucun capteur. */
export type EmptyKind = 'connecting' | 'replaying' | 'waiting' | 'disconnected'

export const EMPTY_LABEL: Record<EmptyKind, string> = {
  connecting: 'Connexion au flux…',
  replaying: 'Rejeu de l’historique…',
  waiting: 'En attente de données…',
  disconnected: 'Flux interrompu',
}

export const DISCONNECTED_TEXT = `${EMPTY_LABEL.disconnected} — ${RECONNECT_TEXT}`

/** null si des capteurs sont connus ; `waiting` : flux ouvert mais muet depuis
 * plusieurs secondes. */
export function emptyKind(empty: boolean, status: ConnectionStatus, waiting: boolean): EmptyKind | null {
  if (!empty) return null
  if (waiting) return 'waiting'
  return status === 'live' ? 'replaying' : status
}
