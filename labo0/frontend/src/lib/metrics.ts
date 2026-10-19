/** Metadonnees d'affichage : seule table des topics cote dashboard. */

import type { Polarity } from '../types'

export interface TopicMeta {
  label: string
  shortLabel: string
  polarity: Polarity
  decimals: number
}

const TOPIC_META: Record<string, TopicMeta> = {
  'gridd.obs.environmental.temperature': { label: 'Température', shortLabel: 'Temp.', polarity: 'neutral', decimals: 1 },
  'gridd.obs.environmental.humidity': { label: 'Humidité', shortLabel: 'Hum.', polarity: 'neutral', decimals: 0 },
  'gridd.obs.environmental.co2': { label: 'CO₂', shortLabel: 'CO₂', polarity: 'lower-better', decimals: 0 },
  'gridd.obs.acoustic.sound_level': { label: 'Niveau sonore', shortLabel: 'Bruit', polarity: 'lower-better', decimals: 1 },
  'gridd.obs.occupancy.count': { label: 'Occupation', shortLabel: 'Occ.', polarity: 'neutral', decimals: 0 },
}

/** Topic inconnu : dernier segment capitalise, comme le backend (« Wind speed »). */
function fallbackLabel(name: string): string {
  const last = name.split('.').slice(-1)[0].replace(/_/g, ' ')
  return last.charAt(0).toUpperCase() + last.slice(1)
}

export function getTopicMeta(name: string | null): TopicMeta {
  if (name !== null) {
    const meta = TOPIC_META[name]
    if (meta) return meta
  }
  const label = name ? fallbackLabel(name) : ''
  return { label, shortLabel: label, polarity: 'neutral', decimals: 1 }
}

export const topicLabel = (name: string): string => getTopicMeta(name).label

export const topicShortLabel = (name: string): string => getTopicMeta(name).shortLabel
