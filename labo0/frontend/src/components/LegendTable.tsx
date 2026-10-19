import { memo } from 'react'
import { FreshnessBadge } from './FreshnessBadge'
import { SeverityIcon } from './SeverityIcon'
import { useMediaQuery } from '../hooks/useMediaQuery'
import type { SensorDerived } from '../hooks/useSeriesStats'
import { alertText, SEVERITY_SR } from '../lib/alerts'
import { fmtValue } from '../lib/format'
import type { Alert, SensorSeries } from '../types'

interface Props {
  sensorIds: string[]
  sensors: Record<string, SensorSeries>
  slots: Record<string, number>
  names: Record<string, string>
  byId: Record<string, SensorDerived>
  unit: string
  decimals: number
  selected: string | 'all'
  hovered: string | null
  /** Alertes actives du topic par node_id. */
  alerts: Record<string, Alert>
  now: number
  onToggle: (id: string) => void
  onHover: (id: string | null) => void
}

/** Legende-tableau sous le graphe : identite par cle-ligne, statistiques sur
 * la plage, fraicheur et emplacement. Toujours rendue (>= 2 series). Capteur
 * en alerte : icone de severite apres le nom (message en title, severite et
 * message en texte sr-only). */
export const LegendTable = memo(function LegendTable({
  sensorIds, sensors, slots, names, byId, unit, decimals, selected, hovered, alerts, now, onToggle, onHover,
}: Props) {
  // Badge de fraicheur compact jusqu'a 560 px : entre 420 et 560 px, Min et Max
  // s'affichent deja et le libelle long tronquerait les noms de capteur.
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
            const name = names[id] ?? id
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
                    <span className="key" style={{ background: `var(--series-${slots[id] ?? 1})` }} aria-hidden="true" />
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
                    {/* node_id seulement s'il apporte une information (nom de repli = id) */}
                    {!name.includes(id) && <span className="legend__id" title={id}>{id}</span>}
                  </span>
                </td>
                <td className="num legend__last">{stats ? fmtValue(stats.last, decimals, unit) : '—'}</td>
                <td className="num col-sm">{stats ? fmtValue(stats.min, decimals) : '—'}</td>
                <td className="num col-sm">{stats ? fmtValue(stats.max, decimals) : '—'}</td>
                <td className="num col-md">{stats ? fmtValue(stats.mean, decimals) : '—'}</td>
                <td className="col-fresh">
                  <FreshnessBadge lastT={lastT} period={derived?.period ?? 60_000} now={now} compact={compact} />
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
