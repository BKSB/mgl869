import { useMemo } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import type { TimeRange } from './RangePicker'
import type { SensorSeries } from '../types'

interface Props {
  /** Series par capteur (node_id -> points + dernier message). */
  sensors: Record<string, SensorSeries>
  /** Capteur affiche, ou 'all' pour une serie par capteur. */
  selected: string | 'all'
  /** Slot couleur (1-8) stable par capteur. */
  colorSlots: Record<string, number>
  /** Nom lisible de chaque capteur (affiche dans l'infobulle). */
  names: Record<string, string>
  /** Fenetre temporelle affichee ('all' = tout l'historique). */
  range: TimeRange
}

const timeFmt = (t: number) =>
  new Date(t).toLocaleTimeString('fr-CA', { hour12: false })

/**
 * Le grand graphe du topic. En mode 'all', les points de tous les capteurs
 * sont fusionnes sur l'axe du temps (format large : une colonne par capteur,
 * connectNulls relie les instants ou un capteur n'a pas publie).
 */
export function TopicChart({ sensors, selected, colorSlots, names, range }: Props) {
  const ids = useMemo(
    () => (selected === 'all' ? Object.keys(sensors).sort() : [selected]),
    [sensors, selected],
  )

  const data = useMemo(() => {
    const rows: Record<number, Record<string, number>> = {}
    for (const id of ids) {
      for (const { t, v } of sensors[id]?.points ?? []) {
        ;(rows[t] ??= { t })[id] = v
      }
    }
    const sorted = Object.values(rows).sort((a, b) => a.t - b.t)
    if (range === 'all' || sorted.length === 0) return sorted
    // Fenetre glissante ancree sur le dernier point recu (pas sur l'horloge
    // du navigateur : les timestamps viennent des capteurs)
    const cutoff = sorted[sorted.length - 1].t - range
    return sorted.filter((row) => row.t >= cutoff)
  }, [sensors, ids, range])

  const unit = sensors[ids[0]]?.last.unit ?? ''

  return (
    <div className="chart-area">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 12, right: 16, bottom: 4, left: 0 }}>
        <CartesianGrid stroke="var(--gridline)" vertical={false} />
        <XAxis
          dataKey="t" type="number" scale="time"
          domain={['dataMin', 'dataMax']}
          tickFormatter={timeFmt} minTickGap={80}
          stroke="var(--baseline)" tick={{ fill: 'var(--muted)', fontSize: 11 }}
          tickLine={false}
        />
        <YAxis
          domain={['auto', 'auto']} width={48}
          stroke="transparent" tick={{ fill: 'var(--muted)', fontSize: 11 }}
          tickLine={false}
          unit={unit ? ` ${unit}` : undefined}
        />
        <Tooltip
          labelFormatter={(t) => timeFmt(Number(t))}
          formatter={(v, name) => [`${v} ${unit}`, String(name)]}
          contentStyle={{
            background: 'var(--surface-1)', border: '1px solid var(--border)',
            borderRadius: 6, color: 'var(--text-primary)', fontSize: 12,
          }}
          cursor={{ stroke: 'var(--baseline)', strokeDasharray: '3 3' }}
        />
        {ids.map((id) => (
          <Line
            key={id} dataKey={id} name={names[id] ?? id} type="monotone" connectNulls
            stroke={`var(--series-${colorSlots[id] ?? 1})`} strokeWidth={2}
            dot={false} isAnimationActive={false}
          />
        ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
