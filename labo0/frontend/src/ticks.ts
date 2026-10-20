/** Graduations des axes du graphe (pur rendu : les donnees viennent du backend). */

import { fmtTickDay, fmtTickTime } from './format'

const MINUTE = 60_000
const HOUR = 3_600_000
const DAY = 86_400_000

/** Valeurs « rondes » (1, 2, 2,5, 5 x 10^n) couvrant [min, max], `count` au plus environ. */
export function niceTicks(min: number, max: number, count = 6): number[] {
  if (!(max > min)) return [min]
  const raw = (max - min) / count
  const magnitude = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ?? 10 * magnitude
  const ticks: number[] = []
  for (let i = Math.ceil(min / step - 1e-9); i * step <= max + step * 1e-9; i++) {
    ticks.push(Number((i * step).toPrecision(12)))
  }
  return ticks
}

export interface TimeTick {
  t: number
  label: string
}

const STEPS = [5 * MINUTE, 10 * MINUTE, 15 * MINUTE, 30 * MINUTE, HOUR, 2 * HOUR, 3 * HOUR, 6 * HOUR, 12 * HOUR, DAY, 2 * DAY, 7 * DAY]

/** Au plus `max` graduations : pas infra-journalier aligne sur l'heure
 * (libelle HH:mm), sinon un jour sur n a minuit local (« ven. 9 »). */
export function timeTicks(from: number, to: number, max = 8): TimeTick[] {
  if (!(to > from)) return []
  const step = STEPS.find((s) => (to - from) / s <= max) ?? 7 * DAY
  const ticks: TimeTick[] = []
  if (step < DAY) {
    for (let t = Math.ceil(from / step) * step; t <= to; t += step) ticks.push({ t, label: fmtTickTime(t) })
    return ticks
  }
  const midnight = new Date(from)
  midnight.setHours(0, 0, 0, 0)
  if (midnight.getTime() < from) midnight.setDate(midnight.getDate() + 1)
  for (let d = midnight; d.getTime() <= to; d.setDate(d.getDate() + step / DAY)) {
    ticks.push({ t: d.getTime(), label: fmtTickDay(d.getTime()) })
  }
  return ticks
}
