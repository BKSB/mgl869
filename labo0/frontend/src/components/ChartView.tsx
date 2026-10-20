import { Fragment } from 'react'
import { fmtDayTime } from '../format'
import { roomHash } from '../route'
import type { ChartData } from '../types'
import { Overview } from './Overview'
import { EmptyState, Segmented } from './StatusBadge'
import { TimeChart } from './TimeChart'

const MIN_ZOOM_MS = 60_000

interface Props {
  data: ChartData | null
  site: string
  range: string
  onRange: (id: string) => void
  zoom: [number, number] | null
  onZoom: (zoom: [number, number] | null) => void
}

/** Vue plein ecran d'un capteur : serie, seuils et statistiques du backend ;
 * le zoom ne fait que filtrer l'affichage (et borne les statistiques). */
export function ChartView({ data, site, range, onRange, zoom, onZoom }: Props) {
  if (!data) return <EmptyState text="Chargement…" />
  const { chart } = data
  if (!chart) {
    return (
      <section className="chart-page">
        <a className="btn" href="#/rooms">
          Retour
        </a>
        <EmptyState text="Capteur introuvable." />
      </section>
    )
  }
  const [from, to] = chart.span
  const window: [number, number] = zoom ? [Math.max(from, zoom[0]), Math.min(to, zoom[1])] : [from, to]
  const back = roomHash(chart.room.id)

  const zoomBy = (factor: number) => {
    const center = (window[0] + window[1]) / 2
    const half = ((window[1] - window[0]) * factor) / 2
    const next: [number, number] = [Math.round(Math.max(from, center - half)), Math.round(Math.min(to, center + half))]
    if (next[1] - next[0] >= to - from) onZoom(null)
    else if (next[1] - next[0] >= MIN_ZOOM_MS) onZoom(next)
  }

  return (
    <section className="chart-page">
      <header className="chart-head">
        <a className="btn btn--back" href={back}>
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="M10 3 5 8l5 5" />
          </svg>
          Retour à la pièce
        </a>
        <div className="chart-heading">
          <h1 className="chart-title">
            {chart.label} · {chart.room.name}
          </h1>
          <div className="chart-sub">
            <code>{chart.sensor_id}</code>
            {site && ` · ${site}`}
            {chart.room.floor && ` · ${chart.room.floor}`}
            {' · valeur actuelle '}
            <span className={`mono text-${chart.status}`}>
              {chart.value_text}
              {chart.unit && ` ${chart.unit}`}
            </span>
          </div>
        </div>
        <a className="icon-btn chart-close" href={back} aria-label="Fermer">
          ×
        </a>
      </header>

      <div className="chart-controls">
        <Segmented options={chart.ranges} value={range} onChange={onRange} label="Plage" />
        <span className={`zoom-pill${zoom ? ' is-active' : ''}`}>
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <circle cx="7" cy="7" r="4.5" />
            <path d="m10.5 10.5 3 3" />
          </svg>
          {zoom ? `Zoom : ${fmtDayTime(window[0])} → ${fmtDayTime(window[1])}` : `Toute la plage · ${chart.range_label}`}
        </span>
        <div className="chart-actions">
          <button type="button" className="icon-btn" aria-label="Zoom avant" title="Zoom avant" onClick={() => zoomBy(0.5)}>
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <circle cx="7" cy="7" r="4.5" />
              <path d="m10.5 10.5 3 3M5 7h4M7 5v4" />
            </svg>
          </button>
          <button type="button" className="icon-btn" aria-label="Zoom arrière" title="Zoom arrière" onClick={() => zoomBy(2)} disabled={!zoom}>
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <circle cx="7" cy="7" r="4.5" />
              <path d="m10.5 10.5 3 3M5 7h4" />
            </svg>
          </button>
          <button type="button" className="btn" onClick={() => onZoom(null)} disabled={!zoom}>
            Réinitialiser le zoom
          </button>
          <a className="btn" href={chart.csv_url} download>
            Exporter CSV
          </a>
        </div>
      </div>

      {chart.stats ? (
        <div className="stat-grid">
          <div className="stat">
            <div className="stat-label">Min ({chart.stats.scope})</div>
            <div className="stat-value">
              <span className={`mono text-${chart.stats.min.status}`}>{chart.stats.min.text}</span>
              {chart.unit && <span className="stat-unit">{chart.unit}</span>}
            </div>
          </div>
          <div className="stat">
            <div className="stat-label">Max ({chart.stats.scope})</div>
            <div className="stat-value">
              <span className={`mono text-${chart.stats.max.status}`}>{chart.stats.max.text}</span>
              {chart.unit && <span className="stat-unit">{chart.unit}</span>}
            </div>
          </div>
          <div className="stat">
            <div className="stat-label">Moyenne ({chart.stats.scope})</div>
            <div className="stat-value">
              <span className="mono">{chart.stats.mean.text}</span>
              {chart.unit && <span className="stat-unit">{chart.unit}</span>}
            </div>
          </div>
          <div className="stat">
            <div className="stat-label">Alertes sur la période</div>
            <div className="stat-value stat-value--text">
              {chart.stats.alerts.map((item, i) => (
                <Fragment key={item.status}>
                  {i > 0 && <span className="stat-sep"> · </span>}
                  <span className={`text-${item.status}`}>{item.text}</span>
                </Fragment>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <EmptyState text="Aucune donnée sur cette plage." />
      )}

      <div className="chart-card">
        <TimeChart series={chart.series} window={window} thresholds={chart.thresholds} unit={chart.unit} onZoom={(a, b) => onZoom([a, b])} />
      </div>

      <div className="chart-card overview-card">
        <div className="overview-head">
          <span className="overview-title">{chart.overview_label}</span>
          <span className="overview-hint">Glisser sur le graphe pour zoomer · déplacer ou étirer la fenêtre ci-dessous</span>
        </div>
        <Overview series={chart.series} span={chart.span} window={window} onChange={onZoom} />
      </div>
    </section>
  )
}
