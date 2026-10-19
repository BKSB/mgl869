import { useMemo } from 'react'
import type { ChartRow, SensorPoint, SensorSeries, SeriesStats } from '../types'
import type { TimeRange } from '../lib/ranges'
import {
  anchorTime, medianInterval, mergeSeries, normalizePoints, seriesStats, sparkline, windowPoints,
} from '../lib/stats'

/** Derives d'un capteur sur la plage : points fenetres, stats, sparkline et
 * periode d'emission (estimee sur l'historique complet). */
export interface SensorDerived {
  /** Points reels de la fenetre (tries, dedoublonnes). */
  pts: SensorPoint[]
  stats: SeriesStats | null
  spark: number[]
  period: number
  /** Dernier horodatage recu sur l'historique complet (fraicheur). */
  lastT: number | undefined
}

/**
 * Statistiques memoisees par capteur + lignes larges fusionnees pour le graphe
 * et le tableau. `now` n'entre dans aucun memo : la fraicheur est calculee a
 * l'affichage. `sensors` ne change de reference qu'au flush d'un lot non vide,
 * donc `rows` garde sa reference entre deux messages. Les series sont
 * normalisees (tri, doublons) : useTopicStream ajoute les points dans l'ordre
 * de reception, et un rejeu apres reconnexion les duplique.
 */
export function useSeriesStats(
  sensors: Record<string, SensorSeries>,
  ids: string[],
  shownIds: string[],
  range: TimeRange,
): {
  anchorT: number
  byId: Record<string, SensorDerived>
  totalPoints: number
  rows: ChartRow[]
  /** Fraicheur des capteurs affiches (shownIds) : dernier point recu et plus
   * longue periode d'emission. Un capteur isole a la sienne, pas celle des
   * autres capteurs du topic. */
  lastT: number | undefined
  period: number
  /** Largeur de la fenetre d'une ligne fusionnee (ms, voir rowEnd) :
   * max(1 s, periode min / 2) arrondie a la seconde entiere. */
  bucket: number
} {
  const base = useMemo(() => {
    // Passe 1 : series propres et periodes (le seau commun en depend)
    const clean: Record<string, SensorPoint[]> = {}
    const periods: Record<string, number> = {}
    let minPeriod = Infinity
    for (const id of ids) {
      const points = normalizePoints(sensors[id]?.points ?? [])
      clean[id] = points
      const p = medianInterval(points)
      periods[id] = p
      if (p < minPeriod) minPeriod = p
    }
    const half = (Number.isFinite(minPeriod) ? minPeriod : 60_000) / 2
    const bucket = Math.max(1000, Math.round(half / 1000) * 1000)
    const anchorT = anchorTime(clean)
    // Passe 2 : fenetre, stats, sparkline
    const byId: Record<string, SensorDerived> = {}
    for (const id of ids) {
      const points = clean[id]
      const pts = windowPoints(points, range, anchorT)
      byId[id] = {
        pts,
        stats: seriesStats(pts),
        spark: sparkline(pts),
        period: periods[id],
        lastT: points[points.length - 1]?.t,
      }
    }
    return { anchorT, byId, bucket }
  }, [sensors, ids, range])

  const shown = useMemo(() => {
    const src: Record<string, SensorPoint[]> = {}
    const present: string[] = []
    let totalPoints = 0
    let lastT: number | undefined
    let period = 0
    for (const id of shownIds) {
      const d = base.byId[id]
      if (!d) continue
      src[id] = d.pts
      present.push(id)
      totalPoints += d.pts.length
      if (d.lastT !== undefined && (lastT === undefined || d.lastT > lastT)) lastT = d.lastT
      if (d.period > period) period = d.period
    }
    // Lignes regroupees par seau, horodatees a la mesure reelle la plus ancienne
    return { rows: mergeSeries(src, present, base.bucket), totalPoints, lastT, period: period || 60_000 }
  }, [base.byId, base.bucket, shownIds])

  return {
    anchorT: base.anchorT,
    byId: base.byId,
    lastT: shown.lastT,
    period: shown.period,
    bucket: base.bucket,
    rows: shown.rows,
    totalPoints: shown.totalPoints,
  }
}
