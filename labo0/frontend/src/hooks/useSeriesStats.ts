import { useMemo } from 'react'
import type { ChartRow, SensorPoint, SensorSeries, SeriesStats } from '../types'
import type { TimeRange } from '../lib/ranges'
import {
  anchorTime, DEFAULT_PERIOD_MS, medianInterval, mergeSeries, normalizePoints, seriesStats, sparkline, windowPoints,
} from '../lib/stats'

/** Derives d'un capteur sur la plage ; period est estimee sur tout l'historique. */
export interface SensorDerived {
  /** Points reels de la fenetre (tries, dedoublonnes). */
  pts: SensorPoint[]
  stats: SeriesStats | null
  spark: number[]
  period: number
  /** Dernier horodatage recu sur l'historique complet (fraicheur). */
  lastT: number | undefined
}

/** Stats memoisees par capteur + lignes larges du graphe et du tableau. `now` n'entre
 * dans aucun memo (fraicheur calculee a l'affichage) ; `sensors` ne change qu'au flush
 * d'un lot non vide, donc `rows` reste stable entre deux messages. Series normalisees :
 * useTopicStream ne trie pas, et un rejeu apres reconnexion duplique les points. */
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
  /** Premiere mesure de la fenetre parmi les capteurs affiches (duree montree). */
  firstT: number | undefined
  /** Avec period : fraicheur des capteurs affiches ; un capteur isole a la sienne. */
  lastT: number | undefined
  period: number
  /** Fenetre d'une ligne fusionnee (ms, cf. rowEnd) : demi-periode min, 1 s au moins. */
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
    const half = (Number.isFinite(minPeriod) ? minPeriod : DEFAULT_PERIOD_MS) / 2
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
    let firstT: number | undefined
    let lastT: number | undefined
    let period = 0
    for (const id of shownIds) {
      const d = base.byId[id]
      if (!d) continue
      src[id] = d.pts
      present.push(id)
      totalPoints += d.pts.length
      const first = d.stats?.firstT
      if (first !== undefined && (firstT === undefined || first < firstT)) firstT = first
      if (d.lastT !== undefined && (lastT === undefined || d.lastT > lastT)) lastT = d.lastT
      if (d.period > period) period = d.period
    }
    return {
      rows: mergeSeries(src, present, base.bucket), totalPoints, firstT, lastT, period: period || DEFAULT_PERIOD_MS,
    }
  }, [base.byId, base.bucket, shownIds])

  return {
    anchorT: base.anchorT,
    byId: base.byId,
    firstT: shown.firstT,
    lastT: shown.lastT,
    period: shown.period,
    bucket: base.bucket,
    rows: shown.rows,
    totalPoints: shown.totalPoints,
  }
}
