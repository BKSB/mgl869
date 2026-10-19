/** Fenetre temporelle affichee, en millisecondes ('all' = tout l'historique). */
export type TimeRange = number | 'all'

export const RANGE_PRESETS: { label: string; value: TimeRange }[] = [
  { label: '15 min', value: 15 * 60_000 },
  { label: '1 h', value: 60 * 60_000 },
  { label: '3 h', value: 3 * 60 * 60_000 },
  { label: 'Tout', value: 'all' },
]

/** Libelle en minuscules d'une plage, pour les sous-titres et aria-labels. */
export function rangeLabel(r: TimeRange): string {
  if (r === 'all') return 'tout l’historique'
  const preset = RANGE_PRESETS.find((p) => p.value === r)
  if (preset) return preset.label
  const min = Math.round(r / 60_000)
  return min >= 60 ? `${Math.round(min / 60)} h` : `${min} min`
}
