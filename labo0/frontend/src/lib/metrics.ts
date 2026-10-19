/** Metadonnees d'affichage par topic : libelle court (onglets etroits),
 * polarite (sens d'une hausse), decimales et description. labels.ts reste la
 * source des libelles longs. */

import { topicLabel } from './labels'
import type { Polarity } from '../types'

export interface TopicMeta {
  shortLabel: string
  polarity: Polarity
  decimals: number
  description: string
}

const TOPIC_META: Record<string, TopicMeta> = {
  'gridd.obs.environmental.temperature': { shortLabel: 'Temp.', polarity: 'neutral', decimals: 1, description: 'Température ambiante' },
  'gridd.obs.environmental.humidity': { shortLabel: 'Hum.', polarity: 'neutral', decimals: 0, description: 'Humidité relative' },
  'gridd.obs.environmental.co2': { shortLabel: 'CO₂', polarity: 'lower-better', decimals: 0, description: 'Concentration de CO₂' },
  'gridd.obs.acoustic.sound_level': { shortLabel: 'Bruit', polarity: 'lower-better', decimals: 1, description: 'Niveau sonore' },
  'gridd.obs.occupancy.count': { shortLabel: 'Occ.', polarity: 'neutral', decimals: 0, description: 'Personnes présentes' },
}

/** Metadonnees du topic, avec repli neutre pour un topic inconnu. */
export function getTopicMeta(name: string | null): TopicMeta {
  if (name !== null) {
    const meta = TOPIC_META[name]
    if (meta) return meta
  }
  return { shortLabel: name ? topicLabel(name) : '', polarity: 'neutral', decimals: 1, description: '' }
}

export const topicShortLabel = (name: string): string => getTopicMeta(name).shortLabel
