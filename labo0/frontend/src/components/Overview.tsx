import { useRef } from 'react'
import { timeTicks } from '../ticks'
import type { ChartPoint } from '../types'
import { useWidth } from '../useWidth'

const HEIGHT = 112
const PAD = { top: 10, right: 10, bottom: 24, left: 10 }
const HANDLE_PX = 8
const MIN_WINDOW_MS = 60_000

type Mode = 'left' | 'right' | 'move' | 'new'

interface Props {
  series: ChartPoint[]
  span: [number, number]
  window: [number, number]
  /** null : toute la plage */
  onChange: (window: [number, number] | null) => void
}

/** Apercu de toute la plage avec la fenetre de zoom : glisser pour la
 * deplacer, tirer ses poignees pour l'etirer, tracer ailleurs pour en creer
 * une autre. */
export function Overview({ series, span: [from, to], window: [a, b], onChange }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const width = useWidth(ref)
  const drag = useRef<{ mode: Mode; anchor: number; start: [number, number] } | null>(null)

  const W = Math.max(width, 320)
  const x0 = PAD.left
  const x1 = W - PAD.right
  const y0 = PAD.top
  const y1 = HEIGHT - PAD.bottom
  const values = series.map((p) => p[1])
  let min = values.length ? Math.min(...values) : 0
  let max = values.length ? Math.max(...values) : 1
  if (max === min) {
    min -= 1
    max += 1
  }
  const sx = (t: number) => x0 + ((t - from) / (to - from)) * (x1 - x0)
  const sy = (v: number) => y1 - ((v - min) / (max - min)) * (y1 - y0)
  const tAt = (px: number) => Math.round(from + ((px - x0) / (x1 - x0)) * (to - from))
  const clamp = (t: number) => Math.min(to, Math.max(from, t))
  const pxAt = (clientX: number) => clientX - (ref.current?.getBoundingClientRect().left ?? 0)

  const line = series.map((p) => `${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join(' ')
  const wx0 = sx(a)
  const wx1 = sx(b)

  const commit = (next: [number, number]) => {
    const [na, nb] = next
    if (nb - na < MIN_WINDOW_MS) return
    onChange(na <= from && nb >= to ? null : [na, nb])
  }

  const onPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId)
    const px = pxAt(e.clientX)
    let mode: Mode = 'new'
    if (Math.abs(px - wx0) <= HANDLE_PX) mode = 'left'
    else if (Math.abs(px - wx1) <= HANDLE_PX) mode = 'right'
    else if (px > wx0 && px < wx1) mode = 'move'
    drag.current = { mode, anchor: tAt(px), start: [a, b] }
  }
  const onPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const state = drag.current
    if (!state) return
    const t = clamp(tAt(pxAt(e.clientX)))
    const [sa, sb] = state.start
    switch (state.mode) {
      case 'left':
        commit([Math.min(t, sb - MIN_WINDOW_MS), sb])
        break
      case 'right':
        commit([sa, Math.max(t, sa + MIN_WINDOW_MS)])
        break
      case 'move': {
        const size = sb - sa
        const start = Math.min(Math.max(from, sa + (t - state.anchor)), to - size)
        commit([start, start + size])
        break
      }
      case 'new':
        commit([Math.min(state.anchor, t), Math.max(state.anchor, t)])
    }
  }
  const onPointerUp = () => {
    drag.current = null
  }

  return (
    <div className="overview-area" ref={ref}>
      <svg
        className="overview-svg"
        width={W}
        height={HEIGHT}
        viewBox={`0 0 ${W} ${HEIGHT}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        role="img"
        aria-label="Fenêtre de zoom"
      >
        {line && <polyline className="overview-line" points={line} />}
        <rect className="overview-dim" x={x0} y={y0} width={Math.max(0, wx0 - x0)} height={y1 - y0} />
        <rect className="overview-dim" x={wx1} y={y0} width={Math.max(0, x1 - wx1)} height={y1 - y0} />
        <rect className="overview-window" x={wx0} y={y0} width={Math.max(0, wx1 - wx0)} height={y1 - y0} />
        <rect className="overview-handle" x={wx0 - 4} y={(y0 + y1) / 2 - 14} width={8} height={28} rx={4} />
        <rect className="overview-handle" x={wx1 - 4} y={(y0 + y1) / 2 - 14} width={8} height={28} rx={4} />
        {timeTicks(from, to, Math.max(3, Math.floor((x1 - x0) / 160))).map((tick) => (
          <text key={tick.t} className="chart-tick" x={sx(tick.t)} y={HEIGHT - 6} textAnchor="middle">
            {tick.label}
          </text>
        ))}
      </svg>
    </div>
  )
}
