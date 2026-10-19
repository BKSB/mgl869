/** Graduations calculees a la main : Recharts 3 (scale="time") cale ses ticks X sur les
 * donnees et, sur un domaine etroit, ses ticks Y tombent entre deux pas de 10^-decimals. */

import { DAY, HOUR, MINUTE } from './time'

/** Pas calendaires candidats, du plus fin au plus large. */
const X_STEPS = [
  1 * MINUTE, 2 * MINUTE, 5 * MINUTE, 10 * MINUTE, 15 * MINUTE, 30 * MINUTE,
  1 * HOUR, 2 * HOUR, 3 * HOUR, 6 * HOUR, 12 * HOUR, DAY,
]

const Y_MANTISSAS = [1, 2, 2.5, 5, 10]
/** Plancher du pas relatif a la grandeur (~4000 ulp) : au-dela de ~2^50, un pas de
 * 10^-decimals serait absorbe (hi + pas === hi) et le domaine ne grandirait plus. */
const Y_MIN_RELATIVE_STEP = 2 ** -40
/** Garde des boucles d'elargissement : la cible est de quelques pas. */
const Y_MAX_WIDEN = 1000

export interface YLadder {
  /** Bornes du domaine, alignees sur le pas. */
  domain: [number, number]
  ticks: number[]
  /** Decimales necessaires pour ecrire le pas (« 26 » si entier, « 24,2 » si 0,2). */
  decimals: number
}

const roundTo = (v: number, decimals: number) => Number(v.toFixed(decimals))

/** Pas = plus petit {1, 2, 2,5, 5} x 10^k >= etendue / target et >= 10^-decimals
 * (jamais deux libelles identiques) ; 2,5 ecarte s'il exige plus de decimales que
 * le topic. Au moins `target` pas (etendue nulle comprise), jamais sous zero si tout
 * est positif ; termine meme sur une sentinelle (capteur bloque a 3,4e38). */
export function yLadder(min: number, max: number, decimals: number, target = 4): YLadder {
  const finite = Number.isFinite(min) && Number.isFinite(max)
  const vMin = finite ? min : 0
  const vMax = finite ? max : 0
  const span = vMax > vMin ? vMax - vMin : 0
  const magnitude = Math.max(Math.abs(vMin), Math.abs(vMax))
  const raw = Math.max(span / target, 10 ** -decimals, magnitude * Y_MIN_RELATIVE_STEP)
  const k = Math.floor(Math.log10(raw) + 1e-9)
  const base = 10 ** k
  let step = 10 * base
  let mantissa = 10
  for (const m of Y_MANTISSAS) {
    if (m === 2.5 && 1 - k > decimals) continue
    if (m * base >= raw - base * 1e-9) { step = m * base; mantissa = m; break }
  }
  const exp = mantissa === 10 ? k + 1 : k
  const stepDecimals = Math.min(3, Math.max(0, -exp + (mantissa === 2.5 ? 1 : 0)))
  step = roundTo(step, stepDecimals)
  let lo = Math.floor(vMin / step + 1e-9) * step
  let hi = Math.ceil(vMax / step - 1e-9) * step
  let goUp = true
  for (let guard = 0; guard < Y_MAX_WIDEN && Math.round((hi - lo) / step) < target; guard++) {
    const canGoDown = !(vMin >= 0 && lo - step < 0)
    if (goUp || !canGoDown) hi += step
    else lo -= step
    goUp = !goUp
  }
  const n = Math.round((hi - lo) / step)
  const ticks: number[] = []
  // + 0 : un tick « -0 » (toFixed d'un -0,0000001) redevient 0
  for (let i = 0; i <= n; i++) ticks.push(roundTo(lo + i * step, stepDecimals) + 0)
  return { domain: [ticks[0], ticks[n]], ticks, decimals: stepDecimals }
}

/** Ticks alignes sur l'heure locale : plus petit pas de X_STEPS donnant au plus
 * `maxTicks` ticks, sinon multiples de jours. Pas < 1 h : multiples de l'epoque
 * (exact pour tout fuseau a la demi-heure) ; sinon depuis minuit local via Date
 * (heure d'ete comprise). Hors [t0, t1] exclus : Recharts ne filtre pas sur le domaine. */
export function xTicks(t0: number, t1: number, maxTicks = 10): number[] {
  const span = t1 - t0
  if (!(span > 0)) return []
  let step = X_STEPS[X_STEPS.length - 1]
  for (const s of X_STEPS) {
    if (span / s <= maxTicks) { step = s; break }
  }
  if (span / step > maxTicks) step = Math.ceil(span / maxTicks / DAY) * DAY
  const out: number[] = []
  if (step < HOUR) {
    for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) out.push(t)
    return out
  }
  const d = new Date(t0)
  d.setHours(0, 0, 0, 0)
  const advance = step >= DAY
    ? () => d.setDate(d.getDate() + step / DAY)
    : () => d.setHours(d.getHours() + step / HOUR)
  for (let guard = 0; guard < 2000 && d.getTime() <= t1; guard++) {
    const t = d.getTime()
    if (t >= t0) out.push(t)
    advance()
  }
  return out
}
