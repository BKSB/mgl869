import { useId, useRef, useState } from 'react'
import { fmtPointTime } from '../format'
import { niceTicks, timeTicks } from '../ticks'
import type { ChartPoint, Status, Threshold } from '../types'
import { useWidth } from '../useWidth'

const HEIGHT = 420
const PAD = { top: 20, right: 28, bottom: 40, left: 72 }
const MIN_DRAG_PX = 4
const NUMBER = new Intl.NumberFormat('fr-CA', { maximumFractionDigits: 2 })
const STATUS_NOTE: Record<Status, string> = {
  normal: '',
  warning: 'seuil warning dépassé',
  critical: 'seuil erreur dépassé',
}

interface Props {
  series: ChartPoint[]
  /** Fenetre affichee [debut, fin] (zoom ou plage entiere) */
  window: [number, number]
  thresholds: Threshold[]
  unit: string
  onZoom: (from: number, to: number) => void
}

/** Graphe principal : la serie du backend filtree a la fenetre, seuils en
 * pointilles, infobulle au survol, glisser pour zoomer. */
export function TimeChart({ series, window: [from, to], thresholds, unit, onZoom }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const width = useWidth(ref)
  const clipId = useId()
  const [hover, setHover] = useState<ChartPoint | null>(null)
  const [drag, setDrag] = useState<[number, number] | null>(null)

  const W = Math.max(width, 320)
  const x0 = PAD.left
  const x1 = W - PAD.right
  const y0 = PAD.top
  const y1 = HEIGHT - PAD.bottom

  // Points de la fenetre, plus un voisin de chaque cote : la ligne continue jusqu'aux bords
  let lo = series.findIndex((p) => p[0] >= from)
  if (lo < 0) lo = series.length
  let hi = series.length - 1
  while (hi >= 0 && series[hi][0] > to) hi--
  const inside = series.slice(lo, hi + 1)
  const drawn = series.slice(Math.max(0, lo - 1), Math.min(series.length, hi + 2))

  const values = [...inside.map((p) => p[1]), ...thresholds.map((t) => t.value)]
  let min = values.length ? Math.min(...values) : 0
  let max = values.length ? Math.max(...values) : 1
  if (max === min) {
    min -= 1
    max += 1
  }
  const margin = (max - min) * 0.08
  min -= margin
  max += margin
  const sx = (t: number) => x0 + ((t - from) / (to - from)) * (x1 - x0)
  const sy = (v: number) => y1 - ((v - min) / (max - min)) * (y1 - y0)
  const tAt = (clientX: number) => {
    const rect = ref.current?.getBoundingClientRect()
    const px = clientX - (rect?.left ?? 0)
    return from + ((px - x0) / (x1 - x0)) * (to - from)
  }
  const pxAt = (clientX: number) => clientX - (ref.current?.getBoundingClientRect().left ?? 0)

  const line = drawn.map((p) => `${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`)
  const area = drawn.length
    ? `M${sx(drawn[0][0]).toFixed(1)},${y1} L${line.join(' L')} L${sx(drawn[drawn.length - 1][0]).toFixed(1)},${y1} Z`
    : ''
  const yTicks = niceTicks(min, max, 6)
  const xTicks = timeTicks(from, to, Math.max(3, Math.floor((x1 - x0) / 110)))

  const nearest = (clientX: number): ChartPoint | null => {
    if (inside.length === 0) return null
    const t = tAt(clientX)
    let best = inside[0]
    for (const p of inside) if (Math.abs(p[0] - t) < Math.abs(best[0] - t)) best = p
    return best
  }

  const onPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId)
    const px = pxAt(e.clientX)
    setDrag([px, px])
  }
  const onPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const px = pxAt(e.clientX)
    if (drag) setDrag([drag[0], px])
    setHover(nearest(e.clientX))
  }
  const onPointerUp = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!drag) return
    const [a, b] = [Math.min(drag[0], pxAt(e.clientX)), Math.max(drag[0], pxAt(e.clientX))]
    setDrag(null)
    if (b - a < MIN_DRAG_PX) return
    const left = ref.current?.getBoundingClientRect().left ?? 0
    onZoom(Math.round(tAt(a + left)), Math.round(tAt(b + left)))
  }

  const tooltipLeft = hover ? Math.min(sx(hover[0]) + 14, W - 190) : 0
  const tooltipTop = hover ? Math.max(8, sy(hover[1]) - 72) : 0

  return (
    <div className="chart-area" ref={ref}>
      <svg
        className={`chart-svg${drag ? ' is-dragging' : ''}`}
        width={W}
        height={HEIGHT}
        viewBox={`0 0 ${W} ${HEIGHT}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => setDrag(null)}
        onPointerLeave={() => setHover(null)}
        role="img"
        aria-label="Historique du capteur"
      >
        <defs>
          <clipPath id={clipId}>
            <rect x={x0} y={y0} width={x1 - x0} height={y1 - y0} />
          </clipPath>
        </defs>
        {thresholds.map((th, i) => {
          const y = Math.min(y1, Math.max(y0, sy(th.value)))
          const top = th.direction === 'above' ? y0 : y
          const bottom = th.direction === 'above' ? y : y1
          return <rect key={`band-${i}`} className={`chart-band chart-band--${th.severity}`} x={x0} y={top} width={x1 - x0} height={Math.max(0, bottom - top)} />
        })}
        {yTicks.map((v) => (
          <g key={v}>
            <line className="chart-grid" x1={x0} x2={x1} y1={sy(v)} y2={sy(v)} />
            <text className="chart-tick" x={x0 - 10} y={sy(v)} textAnchor="end" dominantBaseline="middle">
              {NUMBER.format(v)}
            </text>
          </g>
        ))}
        {xTicks.map((tick) => (
          <g key={tick.t}>
            <line className="chart-grid chart-grid--v" x1={sx(tick.t)} x2={sx(tick.t)} y1={y0} y2={y1} />
            <text className="chart-tick" x={sx(tick.t)} y={y1 + 22} textAnchor="middle">
              {tick.label}
            </text>
          </g>
        ))}
        <g clipPath={`url(#${clipId})`}>
          {area && <path className="chart-fill" d={area} />}
          {line.length > 1 ? <polyline className="chart-line" points={line.join(' ')} /> : null}
        </g>
        {thresholds.map((th, i) => {
          const y = sy(th.value)
          if (y < y0 || y > y1) return null
          return (
            <g key={`th-${i}`} className={`chart-threshold chart-threshold--${th.severity}`}>
              <line x1={x0} x2={x1} y1={y} y2={y} />
              <text x={x1 - 6} y={y - 7} textAnchor="end">
                {th.label}
              </text>
            </g>
          )
        })}
        {hover && (
          <g className="chart-hover">
            <line x1={sx(hover[0])} x2={sx(hover[0])} y1={y0} y2={y1} />
            <circle className={`chart-dot chart-dot--${hover[2]}`} cx={sx(hover[0])} cy={sy(hover[1])} r={6} />
          </g>
        )}
        {drag && Math.abs(drag[1] - drag[0]) >= MIN_DRAG_PX && (
          <rect className="chart-selection" x={Math.min(...drag)} y={y0} width={Math.abs(drag[1] - drag[0])} height={y1 - y0} />
        )}
      </svg>
      {hover && !drag && (
        <div className="chart-tooltip" style={{ left: tooltipLeft, top: tooltipTop }}>
          <div className="chart-tooltip-time">{fmtPointTime(hover[0])}</div>
          <div className={`chart-tooltip-value mono text-${hover[2]}`}>
            {hover[3]}
            {unit && ` ${unit}`}
          </div>
          {STATUS_NOTE[hover[2]] && <div className={`chart-tooltip-note text-${hover[2]}`}>{STATUS_NOTE[hover[2]]}</div>}
        </div>
      )}
      {inside.length === 0 && <div className="chart-empty">Aucune donnée sur cette fenêtre</div>}
    </div>
  )
}
