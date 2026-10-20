import type { Status, Threshold } from '../types'

const W = 300
const H = 56
const PAD = 3

interface Props {
  points: [number, number][]
  thresholds: Threshold[]
  status: Status
}

/** Serie et seuils dans la meme echelle : un seuil hors de la serie reste
 * visible (ligne pointillee), comme sur les maquettes. */
export function Sparkline({ points, thresholds, status }: Props) {
  if (points.length === 0) return <div className="spark spark--empty" aria-hidden="true" />
  const values = [...points.map((p) => p[1]), ...thresholds.map((t) => t.value)]
  let min = Math.min(...values)
  let max = Math.max(...values)
  if (max === min) {
    min -= 1
    max += 1
  }
  const t0 = points[0][0]
  const span = points[points.length - 1][0] - t0 || 1
  const x = (t: number) => (PAD + ((t - t0) / span) * (W - 2 * PAD)).toFixed(1)
  const y = (v: number) => (PAD + ((max - v) / (max - min)) * (H - 2 * PAD)).toFixed(1)
  const line = points.map(([t, v]) => `${x(t)},${y(v)}`)
  const area = `M${x(t0)},${H} L${line.join(' L')} L${x(points[points.length - 1][0])},${H} Z`

  return (
    <svg className={`spark spark--${status}`} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
      <path className="spark-area" d={area} />
      {thresholds.map((th, i) => (
        <line key={i} className={`spark-threshold spark-threshold--${th.severity}`} x1={0} x2={W} y1={y(th.value)} y2={y(th.value)} />
      ))}
      {points.length === 1 ? (
        <circle className="spark-dot" cx={x(t0)} cy={y(points[0][1])} r={2} />
      ) : (
        <polyline className="spark-line" points={line.join(' ')} />
      )}
    </svg>
  )
}
