/** Formateurs fr-CA (virgule decimale, espace fine), mis en cache. */

/** Espace fine insecable (U+202F) entre valeur et unite ; echappement explicite
 * pour qu'un editeur ou un formateur ne la normalise pas en espace simple. */
const THIN = '\u202F'
const MINUS = '\u2212'

const numberFormats = new Map<string, Intl.NumberFormat>()

function numberFormat(decimals: number, signed: boolean): Intl.NumberFormat {
  const key = `${decimals}:${signed ? 's' : 'u'}`
  let f = numberFormats.get(key)
  if (!f) {
    f = new Intl.NumberFormat('fr-CA', {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
      signDisplay: signed ? 'exceptZero' : 'auto',
    })
    numberFormats.set(key, f)
  }
  return f
}

/** Vrai signe moins (U+2212) quel que soit le moteur ICU. */
const withMinus = (s: string) => s.replace(/^-/, MINUS)

/** Valeur qui s'arrondit a zero (y compris -0) : ramenee a 0 avant formatage,
 * sinon Intl conserve le signe (« −0,0 °C »). */
export const roundsToZero = (v: number, decimals: number) => Math.abs(v) < 0.5 * 10 ** -decimals

/** « 22,4 °C », « 1 042 ppm » ; unite vide → valeur seule. */
export function fmtValue(v: number, decimals: number, unit?: string): string {
  const s = withMinus(numberFormat(decimals, false).format(roundsToZero(v, decimals) ? 0 : v))
  return unit ? `${s}${THIN}${unit}` : s
}

/** « +0,3 °C », « −12 ppm » (signe sauf zero). */
export function fmtDelta(v: number, decimals: number, unit?: string): string {
  const s = withMinus(numberFormat(decimals, true).format(v))
  return unit ? `${s}${THIN}${unit}` : s
}

/** Variation sous la moitie du dernier chiffre affiche : « stable ». */
export function isStableDelta(delta: number, decimals: number): boolean {
  return roundsToZero(delta, decimals)
}

/** Texte complet d'une variation (« stable » ou « +0,3 °C sur 15 min ») :
 * meme seuil que DeltaText, pour les aria-label. */
export function deltaLabel(delta: number, decimals: number, unit: string, periodLabel: string): string {
  return isStableDelta(delta, decimals) ? 'stable' : `${fmtDelta(delta, decimals, unit)} ${periodLabel}`
}

const pad2 = (n: number) => (n < 10 ? `0${n}` : String(n))

/** « 10:14 » ou « 10:14:06 » (heure locale, zero-paddee). */
export function fmtTime(t: number, withSeconds: boolean): string {
  const d = new Date(t)
  const hm = `${pad2(d.getHours())}:${pad2(d.getMinutes())}`
  return withSeconds ? `${hm}:${pad2(d.getSeconds())}` : hm
}

/** « 2026-10-04 10:14:06 » (heure locale). */
export function fmtDateTime(t: number): string {
  const d = new Date(t)
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${fmtTime(t, true)}`
}

const MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.']

/** « 03 oct. 03:00 » (ou « 03 oct. 03:00:02 ») : jour + heure, quand
 * l'historique affiche couvre plus de 24 h (l'heure seule serait ambigue). */
export function fmtDayTime(t: number, withSeconds = false): string {
  const d = new Date(t)
  return `${pad2(d.getDate())} ${MONTHS[d.getMonth()]} ${fmtTime(t, withSeconds)}`
}

const relative = new Intl.RelativeTimeFormat('fr-CA', { style: 'short', numeric: 'always' })

/** « il y a 5 s », « il y a 4 min », « il y a 1 h » ; age negatif = 0. */
export function fmtAge(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000))
  if (s === 0) return 'à l’instant'
  if (s < 60) return relative.format(-s, 'second')
  const m = Math.round(s / 60)
  if (m < 60) return relative.format(-m, 'minute')
  return relative.format(-Math.round(m / 60), 'hour')
}

/** « 2 h 58 », « 45 min », « 30 s » (duree ecoulee). */
export function fmtDuration(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000))
  if (s < 60) return `${s} s`
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min`
  const h = Math.floor(m / 60)
  const rest = m % 60
  return rest === 0 ? `${h} h` : `${h} h ${pad2(rest)}`
}

const countFormat = new Intl.NumberFormat('fr-CA', { maximumFractionDigits: 0 })

/** Entier avec separateur de milliers : « 1 842 ». */
export function fmtCount(n: number): string {
  return countFormat.format(n)
}
