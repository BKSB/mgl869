/** Statistiques pures derivees des series (sans React) : fenetre, min/max,
 * sparkline, fusion k-voies et fraicheur. Testables isolement. */

import type { ChartRow, Freshness, SensorPoint, SeriesStats } from '../types'
import type { TimeRange } from './ranges'

/** Horloge de reference : le dernier point de toutes les series (triees,
 * voir normalizePoints) ; la fenetre est ancree sur les capteurs, pas sur
 * Date.now(). 0 si vide. */
export function anchorTime(series: Record<string, SensorPoint[]>): number {
  let max = 0
  for (const id in series) {
    const pts = series[id]
    const t = pts[pts.length - 1]?.t ?? 0
    if (t > max) max = t
  }
  return max
}

/**
 * Serie strictement croissante en t, sans doublon. Une passe O(n) quand la
 * serie est deja propre (meme reference renvoyee) ; sinon copie triee puis
 * dedoublonnee en gardant le dernier point d'un meme t (rejeu de l'historique
 * apres reconnexion : memes valeurs). useTopicStream ne trie pas.
 */
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

/**
 * Borne exclusive de la fenetre d'une ligne fusionnee qui commence a t :
 * [t, t + bucket). Les capteurs d'un meme topic n'emettent jamais a la meme
 * milliseconde ; la fenetre est ANCREE sur la premiere mesure reelle de la
 * ligne (pas une grille fixe : une frontiere de grille couperait un groupe
 * de capteurs en deux lignes). Sans seau (bucket <= 0), la ligne ne couvre
 * que l'instant t (horodatages en ms entieres).
 */
export function rowEnd(t: number, bucket: number): number {
  return t + (bucket > 0 ? bucket : 1)
}

/** Index du premier point dont t >= cutoff (recherche binaire, points tries). */
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

/** Points de la fenetre ; 'all' renvoie le tableau d'origine (meme reference). */
export function windowPoints(points: SensorPoint[], range: TimeRange, anchorT: number): SensorPoint[] {
  if (range === 'all') return points
  return points.slice(cutoffIndex(points, anchorT - range))
}

/** Une passe sur la fenetre ; null si elle est vide. */
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

/** Moyenne par seau temporel (12 par defaut) ; seau vide = valeur du seau
 * precedent, les premiers seaux vides prennent la premiere valeur connue. */
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

/**
 * Fusion k-voies de series triees : une ligne par fenetre [tMin, rowEnd), une
 * colonne par capteur. row.t = tMin est l'horodatage REEL de la plus ancienne
 * mesure de la ligne, jamais une valeur arrondie : tableau, CSV et infobulle
 * affichent l'heure d'une vraie mesure. Les points non pris ont tous
 * t >= rowEnd : les lignes sont strictement croissantes et espacees d'au
 * moins un seau. Deux points d'une meme serie dans la fenetre : le dernier
 * gagne. O(N*k), aucun tri global, aucun objet intermediaire.
 */
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

/** Periode d'emission estimee : mediane des k derniers intervalles (60 s par
 * defaut quand la serie est trop courte). */
export function medianInterval(pts: SensorPoint[], k = 20): number {
  const n = pts.length
  if (n < 3) return 60_000
  const m = Math.min(k, n - 1)
  const deltas: number[] = []
  for (let i = n - m; i < n; i++) deltas.push(pts[i].t - pts[i - 1].t)
  deltas.sort((a, b) => a - b)
  const mid = deltas.length >>> 1
  return deltas.length % 2 === 1 ? deltas[mid] : (deltas[mid - 1] + deltas[mid]) / 2
}

/** Fraicheur d'une mesure selon son age et la periode du capteur. Planchers
 * de 30 s / 120 s : la gigue reseau sur les capteurs a 6 s ne doit pas alerter. */
export function freshness(ageMs: number, periodMs: number): Freshness {
  if (ageMs <= Math.max(2 * periodMs, 30_000)) return 'fresh'
  if (ageMs <= Math.max(5 * periodMs, 120_000)) return 'late'
  return 'stale'
}
