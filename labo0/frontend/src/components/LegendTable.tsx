import { memo } from 'react'
import { FreshnessBadge } from './FreshnessBadge'
import { SeriesKey } from './SeriesKey'
import { SeverityIcon } from './SeverityIcon'
import { useMediaQuery } from '../hooks/useMediaQuery'
import type { SensorDerived } from '../hooks/useSeriesStats'
import { alertText, SEVERITY_SR } from '../lib/alerts'
import { fmtValue } from '../lib/format'
import { DEFAULT_PERIOD_MS } from '../lib/stats'
import type { Alert, SensorSeries } from '../types'

interface Props {
  sensorIds: string[]
  sensors: Record<string, SensorSeries>
  slots: Record<string, number>
  names: Record<string, string>
  byId: Record<string, SensorDerived>
  unit: string
  decimals: number
  selected: string | null
  hovered: string | null
  alerts: Record<string, Alert>
  now: number
  onToggle: (id: string) => void
  onHover: (id: string | null) => void
}

export const LegendTable = memo(function LegendTable({
  sensorIds, sensors, slots, names, byId, unit, decimals, selected, hovered, alerts, now, onToggle, onHover,
}: Props) {
  // Compact sous 560 px : avec Min et Max (>= 420 px), le libelle long tronquerait les noms
  const compact = !useMediaQuery('(min-width: 560px)')
  return (
    <div className="legend-wrap">
      <table className="legend">
        <caption className="sr-only">Légende et statistiques par capteur sur la plage</caption>
        <thead>
          <tr>
            <th scope="col">Capteur</th>
            <th scope="col" className="num">Dernière</th>
            <th scope="col" className="num col-sm">Min</th>
            <th scope="col" className="num col-sm">Max</th>
            <th scope="col" className="num col-md">Moy.</th>
            <th scope="col" className="col-fresh">Mis à jour</th>
            <th scope="col" className="col-lg">Emplacement</th>
          </tr>
        </thead>
        <tbody>
          {sensorIds.map((id) => {
            const derived = byId[id]
            const stats = derived?.stats ?? null
            // Dernier point de la serie normalisee (triee, sans doublon de rejeu)
            const lastT = derived?.lastT
            const meta = sensors[id]?.last.metadata
            const name = names[id]
            const alert = alerts[id]
            const message = alert ? alertText(alert) : ''
            const loc = [meta?.building?.label, meta?.storey?.label].filter(Boolean).join(' · ') || '—'
            const cls = [selected === id ? 'is-active' : '', hovered === id ? 'is-hovered' : '']
              .filter(Boolean).join(' ')
            return (
              <tr
                key={id}
                className={cls || undefined}
                onMouseEnter={() => onHover(id)}
                onMouseLeave={() => onHover(null)}
              >
                <td>
                  <span className="legend__sensor">
                    <SeriesKey slot={slots[id]} />
                    <button
                      type="button"
                      className="linkish"
                      title={name}
                      aria-pressed={selected === id}
                      onClick={() => onToggle(id)}
                      onFocus={() => onHover(id)}
                      onBlur={() => onHover(null)}
                    >
                      {name}
                    </button>
                    {alert && (
                      <span className="legend__alert" title={message}>
                        <SeverityIcon severity={alert.severity} size={14} />
                        <span className="sr-only">{SEVERITY_SR[alert.severity]} : {message}</span>
                      </span>
                    )}
                    {/* Pas d'id si le nom le contient deja (nom de repli) */}
                    {!name.includes(id) && <span className="legend__id" title={id}>{id}</span>}
                  </span>
                </td>
                <td className="num legend__last">{stats ? fmtValue(stats.last, decimals, unit) : '—'}</td>
                <td className="num col-sm">{stats ? fmtValue(stats.min, decimals) : '—'}</td>
                <td className="num col-sm">{stats ? fmtValue(stats.max, decimals) : '—'}</td>
                <td className="num col-md">{stats ? fmtValue(stats.mean, decimals) : '—'}</td>
                <td className="col-fresh">
                  <FreshnessBadge lastT={lastT} period={derived?.period ?? DEFAULT_PERIOD_MS} now={now} compact={compact} />
                </td>
                <td className="col-lg legend__loc">{loc}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
})
