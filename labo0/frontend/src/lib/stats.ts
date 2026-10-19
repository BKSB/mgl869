/** Statistiques pures des series (sans React). */

import type { ChartRow, Freshness, SensorPoint, SeriesStats } from '../types'
import type { TimeRange } from './ranges'
import { MINUTE } from './time'

/** Periode d'emission supposee tant que la serie est trop courte pour la mesurer. */
export const DEFAULT_PERIOD_MS = MINUTE

/** Dernier t de toutes les series (triees) : la fenetre est ancree sur les
 * capteurs, pas sur Date.now(). */
export function anchorTime(series: Record<string, SensorPoint[]>): number {
  let max = 0
  for (const id in series) {
    const pts = series[id]
    const t = pts[pts.length - 1]?.t ?? 0
    if (t > max) max = t
  }
  return max
}

/** Strictement croissante en t. Deja propre : meme reference ; sinon copie triee,
 * le dernier point d'un meme t gagnant (rejeu apres reconnexion). */
export function normalizePoints(points: SensorPoint[]): SensorPoint[] {
  let clean = true
  for (let i = 1; i < points.length; i++) {
    if (points[i].t <= points[i - 1].t) { clean = false; break }
  }
  if (clean) return points
  const sorted = [...points].sort((a, b) => a.t - b.t)
  const out: SensorPoint[] = []
  for (const p of sorted) {
    if (out.length > 0 && out[out.length - 1].t === p.t) out[out.length - 1] = p
    else out.push(p)
  }
  return out
}

/** Fin exclusive de la ligne [t, t + bucket) : les capteurs n'emettent jamais a la
 * meme ms. Ancree sur sa premiere mesure, pas sur une grille fixe qui couperait un
 * groupe en deux ; bucket <= 0 : t seul (ms entieres). */
export function rowEnd(t: number, bucket: number): number {
  return t + (bucket > 0 ? bucket : 1)
}

/** Premier index avec t >= cutoff ; points tries. */
export function cutoffIndex(points: SensorPoint[], cutoff: number): number {
  let lo = 0
  let hi = points.length
  while (lo < hi) {
    const mid = (lo + hi) >>> 1
    if (points[mid].t < cutoff) lo = mid + 1
    else hi = mid
  }
  return lo
}

/** 'all' : tableau d'origine (meme reference). */
export function windowPoints(points: SensorPoint[], range: TimeRange, anchorT: number): SensorPoint[] {
  if (range === 'all') return points
  return points.slice(cutoffIndex(points, anchorT - range))
}

export function seriesStats(pts: SensorPoint[]): SeriesStats | null {
  const n = pts.length
  if (n === 0) return null
  const first = pts[0]
  const last = pts[n - 1]
  let min = first.v
  let minT = first.t
  let max = first.v
  let maxT = first.t
  let sum = 0
  for (const { t, v } of pts) {
    sum += v
    if (v < min) { min = v; minT = t }
    if (v > max) { max = v; maxT = t }
  }
  return {
    count: n,
    first: first.v, firstT: first.t,
    last: last.v, lastT: last.t,
    min, minT, max, maxT,
    mean: sum / n,
    delta: last.v - first.v,
  }
}

/** Moyenne par seau temporel ; seau vide : valeur precedente, ou premiere connue. */
export function sparkline(pts: SensorPoint[], buckets = 12): number[] {
  const n = pts.length
  if (n < 2) return []
  const firstT = pts[0].t
  const lastT = pts[n - 1].t
  if (lastT === firstT) return []
  const w = (lastT - firstT) / buckets
  const sums = new Array<number>(buckets).fill(0)
  const counts = new Array<number>(buckets).fill(0)
  for (const { t, v } of pts) {
    const i = Math.min(buckets - 1, Math.floor((t - firstT) / w))
    sums[i] += v
    counts[i] += 1
  }
  let firstKnown = 0
  for (let i = 0; i < buckets; i++) {
    if (counts[i] > 0) { firstKnown = sums[i] / counts[i]; break }
  }
  const out = new Array<number>(buckets)
  let prev = firstKnown
  for (let i = 0; i < buckets; i++) {
    if (counts[i] > 0) prev = sums[i] / counts[i]
    out[i] = prev
  }
  return out
}

/** Fusion k-voies de series triees, une ligne par fenetre [tMin, rowEnd). row.t est
 * l'horodatage reel de la plus ancienne mesure, jamais arrondi : tableau, CSV et
 * infobulle l'affichent. Lignes espacees d'au moins un seau ; dans une fenetre, le
 * dernier point d'une serie gagne. O(N*k). */
export function mergeSeries(byId: Record<string, SensorPoint[]>, ids: string[], bucket = 0): ChartRow[] {
  const k = ids.length
  if (k === 0) return []
  const arrs = ids.map((id) => byId[id] ?? [])
  const idx = new Array<number>(k).fill(0)
  const rows: ChartRow[] = []
  for (;;) {
    let tMin = Infinity
    for (let i = 0; i < k; i++) {
      const p = arrs[i][idx[i]]
      if (p !== undefined && p.t < tMin) tMin = p.t
    }
    if (tMin === Infinity) break
    const end = rowEnd(tMin, bucket)
    const row: ChartRow = { t: tMin }
    for (let i = 0; i < k; i++) {
      const arr = arrs[i]
      while (idx[i] < arr.length && arr[idx[i]].t < end) {
        row[ids[i]] = arr[idx[i]].v
        idx[i] += 1
      }
    }
    rows.push(row)
  }
  return rows
}

/** Periode d'emission : mediane des k derniers intervalles. */
export function medianInterval(pts: SensorPoint[], k = 20): number {
  const n = pts.length
  if (n < 3) return DEFAULT_PERIOD_MS
  const m = Math.min(k, n - 1)
  const deltas: number[] = []
  for (let i = n - m; i < n; i++) deltas.push(pts[i].t - pts[i - 1].t)
  deltas.sort((a, b) => a - b)
  const mid = deltas.length >>> 1
  return deltas.length % 2 === 1 ? deltas[mid] : (deltas[mid - 1] + deltas[mid]) / 2
}

/** Planchers de 30 s / 120 s : la gigue reseau des capteurs a 6 s ne doit pas alerter. */
export function freshness(ageMs: number, periodMs: number): Freshness {
  if (ageMs <= Math.max(2 * periodMs, 30_000)) return 'fresh'
  if (ageMs <= Math.max(5 * periodMs, 120_000)) return 'late'
  return 'stale'
}
