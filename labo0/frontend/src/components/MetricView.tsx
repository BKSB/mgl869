import { roomHash } from '../route'
import type { MetricData } from '../types'
import { SensorTile } from './SensorTile'
import { EmptyState, Segmented, Thresholds } from './StatusBadge'

interface Props {
  data: MetricData | null
  range: string
  onRange: (id: string) => void
  onSort: (id: string) => void
  now: number
}

export function MetricView({ data, range, onRange, onSort, now }: Props) {
  if (!data) return <EmptyState text="Chargement…" />
  const { metrics, metric } = data
  return (
    <section className="content content--page">
      <nav className="pills" aria-label="Type de capteur">
        {metrics.map((m) => (
          <a
            key={m.id}
            className={`pill${m.id === metric?.id ? ' is-active' : ''}`}
            href={`#/metrics/${encodeURIComponent(m.id)}`}
            aria-current={m.id === metric?.id ? 'page' : undefined}
          >
            {m.label}
          </a>
        ))}
      </nav>
      {metric ? (
        <>
          <div className="page-head">
            <div>
              <h1 className="page-title">{metric.label} · toutes les pièces</h1>
              <div className="page-meta">
                <span>{metric.summary}</span>
                {metric.counts.map((c) => (
                  <span key={c.status} className={`text-${c.status}`}>
                    {c.text}
                  </span>
                ))}
                {metric.thresholds.length > 0 && (
                  <span>
                    Seuils : <Thresholds items={metric.thresholds} />
                  </span>
                )}
              </div>
            </div>
            <div className="controls">
              <label className="sort">
                Trier par
                <select value={metric.sort} onChange={(e) => onSort(e.target.value)}>
                  {metric.sorts.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </label>
              <Segmented options={data.ranges} value={range} onChange={onRange} label="Plage" />
            </div>
          </div>
          {metric.sensors.length > 0 ? (
            <div className="tile-grid tile-grid--4">
              {metric.sensors.map((tile) => (
                <SensorTile
                  key={tile.id}
                  tile={tile}
                  title={tile.room.name}
                  subtitle={
                    <>
                      {tile.room.floor && `${tile.room.floor} · `}
                      <code>{tile.id}</code>
                    </>
                  }
                  footer={tile.stats_text}
                  now={now}
                  href={roomHash(tile.room.id)}
                />
              ))}
            </div>
          ) : (
            <EmptyState text="Aucune mesure pour l’instant." />
          )}
          <p className="footnote">Clic sur une tuile → détail de la pièce. Min/max et états fournis par le backend.</p>
        </>
      ) : (
        <EmptyState text="Aucun topic configuré." />
      )}
    </section>
  )
}
