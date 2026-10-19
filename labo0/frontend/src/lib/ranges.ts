import { HOUR, MINUTE } from './time'

/** Fenetre affichee en ms, ou 'all' (tout l'historique). */
export type TimeRange = number | 'all'

export const RANGE_PRESETS: { label: string; value: TimeRange }[] = [
  { label: '15 min', value: 15 * MINUTE },
  { label: '1 h', value: HOUR },
  { label: '3 h', value: 3 * HOUR },
  { label: 'Tout', value: 'all' },
]

/** En minuscules, a inserer dans une phrase (sous-titres, aria-label). */
export function rangeLabel(r: TimeRange): string {
  if (r === 'all') return 'tout l’historique'
  const preset = RANGE_PRESETS.find((p) => p.value === r)
  if (preset) return preset.label
  const min = Math.round(r / MINUTE)
  return min >= 60 ? `${Math.round(min / 60)} h` : `${min} min`
}

/** « Dernières 15 min », « Dernière heure », « Tout l’historique ». */
export function rangeTitle(r: TimeRange): string {
  if (r === 'all') return 'Tout l’historique'
  return r === HOUR ? 'Dernière heure' : `Dernières ${rangeLabel(r)}`
}

/** Periode d'une variation (« +0,3 °C sur 15 min », « sur l’historique »). */
export const deltaRangeLabel = (r: TimeRange): string => (r === 'all' ? 'l’historique' : rangeLabel(r))
