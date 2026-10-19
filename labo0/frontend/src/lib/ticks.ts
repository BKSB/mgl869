/** Graduations « propres » des axes (sans React). Recharts 3 avec
 * scale="time" place ses ticks sur les horodatages des donnees et, sur un
 * domaine etroit, ses ticks Y tombent entre deux pas de 10^-decimals : les
 * echelles sont calculees ici a la main. */

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

/** Pas calendaires candidats, du plus fin au plus large. */
const X_STEPS = [
  1 * MINUTE, 2 * MINUTE, 5 * MINUTE, 10 * MINUTE, 15 * MINUTE, 30 * MINUTE,
  1 * HOUR, 2 * HOUR, 3 * HOUR, 6 * HOUR, 12 * HOUR, DAY,
]

/** Mantisses admises pour l'axe Y (x 10^k). */
const Y_MANTISSAS = [1, 2, 2.5, 5, 10]
/** Pas Y minimal relatif a la grandeur des valeurs (2^-40, ~4 000 ulp) :
 * au-dela d'environ 2^50, un pas de 10^-decimals serait absorbe par
 * l'arrondi flottant (hi + pas === hi) et le domaine ne grandirait plus. */
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

/**
 * Echelle Y : pas = plus petit {1, 2, 2,5, 5} x 10^k >= etendue / target et
 * >= 10^-decimals (jamais plus fin que la precision du topic, donc jamais
 * deux libelles identiques) ; 2,5 x 10^k est ecarte s'il demande plus de
 * decimales que le topic. Bornes arrondies au pas, au moins `target` pas
 * (etendue nulle comprise). Un domaine entierement positif ne descend pas
 * sous zero. Le pas reste representable quelle que soit la grandeur des
 * valeurs (capteur bloque sur une sentinelle, ex. 3,4e38) : l'elargissement
 * termine toujours.
 */
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

/**
 * Graduations X alignees sur l'horloge locale : plus petit pas de X_STEPS
 * donnant au plus `maxTicks` ticks (au-dela de 24 h, multiples de jours).
 * Les pas < 1 h s'alignent sur les multiples de l'epoque (equivalent a
 * l'heure locale pour tout fuseau a la demi-heure) ; les pas >= 1 h partent
 * du minuit local et avancent par Date (heure d'ete comprise). Seuls les
 * ticks dans [t0, t1] sont renvoyes : Recharts ne filtre pas sur le domaine.
 */
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
