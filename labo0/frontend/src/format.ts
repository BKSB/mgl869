/** Seul formatage fait par le frontend : les horodatages, qui dependent du
 * fuseau du navigateur. Les nombres arrivent formates du backend. */

const pad = (n: number): string => String(n).padStart(2, '0')

/** HH:mm:ss local (toLocaleTimeString('fr-CA') rend « 10 h 47 min 50 s »). */
export function fmtTime(ms: number): string {
  const d = new Date(ms)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** « à l’instant », « il y a 2 s », « il y a 3 min », « il y a 2 h », « il y a 3 j ». */
export function fmtAgo(ms: number, now: number): string {
  const s = Math.max(0, Math.round((now - ms) / 1000))
  if (s < 1) return 'à l’instant'
  if (s < 60) return `il y a ${s} s`
  const m = Math.round(s / 60)
  if (m < 60) return `il y a ${m} min`
  const h = Math.round(m / 60)
  if (h < 24) return `il y a ${h} h`
  return `il y a ${Math.round(h / 24)} j`
}
