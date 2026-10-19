import type { TooltipContentProps } from 'recharts'
import { SeriesKey } from './SeriesKey'
import type { SensorDerived } from '../hooks/useSeriesStats'
import { fmtDayTime, fmtTime, fmtValue } from '../lib/format'
import { cutoffIndex, rowEnd } from '../lib/stats'

type Props = Partial<TooltipContentProps<number, string>> & {
  unit: string
  decimals: number
  slots: Record<string, number>
  names: Record<string, string>
  ids: string[]
  byId: Record<string, SensorDerived>
  /** Seau de regroupement des lignes (ms). */
  bucket: number
  longSpan: boolean
}

/** Capteurs non synchrones : chaque serie est lue a sa derniere mesure avant la
 * fin de la ligne survolee, pas dans `payload` ; « — » au-dela de 2 periodes. */
export function ChartTooltip({
  active, payload, label, unit, decimals, slots, names, ids, byId, bucket, longSpan,
}: Props) {
  if (!active || !payload?.length) return null
  const t = Number(label)
  if (!Number.isFinite(t)) return null
  // Meme fenetre que mergeSeries : points de cette ligne et des precedentes
  const end = rowEnd(t, bucket)
  const valued: { id: string; value: number }[] = []
  const missing: { id: string; value?: undefined }[] = []
  for (const id of ids) {
    const d = byId[id]
    let value: number | undefined
    if (d) {
      const k = cutoffIndex(d.pts, end) - 1
      const p = k >= 0 ? d.pts[k] : undefined
      if (p && t - p.t <= 2 * d.period) value = p.v
    }
    if (value === undefined) missing.push({ id })
    else valued.push({ id, value })
  }
  valued.sort((a, b) => b.value - a.value)
  const rows = [...valued, ...missing]
  return (
    <div className="tip">
      <div className="tip__time">{longSpan ? fmtDayTime(t, true) : fmtTime(t, true)}</div>
      <ul>
        {rows.map(({ id, value }) => (
          <li key={id} className={value === undefined ? 'tip__row--none' : undefined}>
            <SeriesKey slot={slots[id]} />
            <strong className="tip__val num">{value === undefined ? '—' : fmtValue(value, decimals, unit)}</strong>
            <span className="tip__name">{names[id]}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
