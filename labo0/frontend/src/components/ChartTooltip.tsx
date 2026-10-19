import type { TooltipContentProps } from 'recharts'
import type { SensorDerived } from '../hooks/useSeriesStats'
import { fmtDayTime, fmtTime, fmtValue } from '../lib/format'
import { cutoffIndex, rowEnd } from '../lib/stats'

type Props = Partial<TooltipContentProps<number, string>> & {
  unit: string
  decimals: number
  slots: Record<string, number>
  names: Record<string, string>
  /** Capteurs traces, dans l'ordre d'affichage. */
  ids: string[]
  byId: Record<string, SensorDerived>
  /** Seau de regroupement des lignes (ms), pour retrouver le point reel. */
  bucket: number
  /** Historique > 24 h : horodatage avec la date. */
  longSpan: boolean
}

/**
 * Infobulle du graphe : horodatage, puis une ligne par serie tracee (valeur
 * d'abord, nom ensuite, cle-ligne), triees par valeur decroissante. Les
 * capteurs n'emettent pas au meme instant : plutot que le seul `payload` de
 * la ligne survolee, chaque serie est echantillonnee a sa derniere mesure
 * avant la fin de la fenetre de la ligne, [label, label + bucket) (« — » si
 * elle date de plus de 2 periodes). `label` est l'heure reelle de la plus
 * ancienne mesure de la ligne.
 */
export function ChartTooltip({
  active, payload, label, unit, decimals, slots, names, ids, byId, bucket, longSpan,
}: Props) {
  if (!active || !payload?.length) return null
  const t = Number(label)
  if (!Number.isFinite(t)) return null
  const rows: { key: string; value: number }[] = []
  const missing: string[] = []
  // Meme fenetre que mergeSeries : points de cette ligne et des precedentes
  const end = rowEnd(t, bucket)
  for (const id of ids) {
    const d = byId[id]
    let value: number | undefined
    if (d) {
      const k = cutoffIndex(d.pts, end) - 1
      const p = k >= 0 ? d.pts[k] : undefined
      if (p && t - p.t <= 2 * d.period) value = p.v
    }
    if (value === undefined) missing.push(id)
    else rows.push({ key: id, value })
  }
  rows.sort((a, b) => b.value - a.value)
  return (
    <div className="tip">
      <div className="tip__time">{longSpan ? fmtDayTime(t, true) : fmtTime(t, true)}</div>
      <ul>
        {rows.map(({ key, value }) => (
          <li key={key}>
            <span className="key" style={{ background: `var(--series-${slots[key] ?? 1})` }} aria-hidden="true" />
            <strong className="tip__val num">{fmtValue(value, decimals, unit)}</strong>
            <span className="tip__name">{names[key] ?? key}</span>
          </li>
        ))}
        {missing.map((key) => (
          <li key={key} className="tip__row--none">
            <span className="key" style={{ background: `var(--series-${slots[key] ?? 1})` }} aria-hidden="true" />
            <strong className="tip__val num">—</strong>
            <span className="tip__name">{names[key] ?? key}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
