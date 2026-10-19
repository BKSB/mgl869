import { memo } from 'react'
import { DeltaText } from './DeltaText'
import { SeverityIcon } from './SeverityIcon'
import { Sparkline } from './Sparkline'
import { alertText, SEVERITY_SR } from '../lib/alerts'
import { deltaLabel, fmtValue } from '../lib/format'
import type { Alert, Polarity, SeriesStats } from '../types'

interface Props {
  id: string
  name: string
  slot: number
  unit: string
  decimals: number
  stats: SeriesStats | null
  spark: number[]
  polarity: Polarity
  rangeLabel: string
  active: boolean
  dimmed: boolean
  hovered: boolean
  /** Alerte active du capteur (topic affiche), s'il y en a une. */
  alert?: Alert
  onToggle: (id: string) => void
  onHover: (id: string | null) => void
}

/** Tile par capteur : cle-ligne + nom, valeur, delta, sparkline. Bouton
 * bascule aria-pressed qui isole le capteur ; le nom accessible vient de
 * l'aria-label et reste stable (l'etat enfonce dit deja si le capteur est
 * isole), l'action est dans le title (description accessible). Capteur en
 * alerte : bordure 1 px couleur de statut, icone de severite (message en
 * title) ; severite et message sont dans l'aria-label, puisque le contenu
 * visuel est aria-hidden. */
export const StatTile = memo(function StatTile({
  id, name, slot, unit, decimals, stats, spark, polarity, rangeLabel, active, dimmed, hovered, alert, onToggle, onHover,
}: Props) {
  const action = active ? 'Afficher tous les capteurs (Échap)' : 'Isoler ce capteur'
  // Meme texte que DeltaText (« stable » sous le seuil d'affichage)
  const summary = stats
    ? `${fmtValue(stats.last, decimals, unit)}, ${deltaLabel(stats.delta, decimals, unit, `sur ${rangeLabel}`)}`
    : 'aucune mesure dans la plage'
  const message = alert ? alertText(alert) : ''
  const alertLabel = alert ? `${SEVERITY_SR[alert.severity]} : ${message}, ` : ''
  const cls = [
    'tile', active ? 'tile--active' : '', dimmed ? 'tile--dimmed' : '', hovered ? 'tile--hovered' : '',
    alert ? `tile--alert tile--alert-${alert.severity}` : '',
  ].filter(Boolean).join(' ')
  return (
    <button
      type="button"
      className={cls}
      aria-pressed={active}
      aria-label={`${name}, ${alertLabel}${summary}`}
      title={action}
      onClick={() => onToggle(id)}
      onMouseEnter={() => onHover(id)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(id)}
      onBlur={() => onHover(null)}
    >
      <span aria-hidden="true" className="tile__head">
        <span className="tile__label">
          <span className="key" style={{ background: `var(--series-${slot})` }} />
          <span className="tile__name">{name}</span>
          {alert && (
            <span className="tile__alert" title={message}>
              <SeverityIcon severity={alert.severity} size={14} />
            </span>
          )}
        </span>
        {!name.includes(id) && <span className="tile__id" title={id}>{id}</span>}
      </span>
      <span aria-hidden="true" className="tile__body">
        <span className="tile__value">
          {stats ? fmtValue(stats.last, decimals) : '—'}
          {stats && unit && <span className="tile__unit">{unit}</span>}
        </span>
        {stats && spark.length >= 2 && (
          <span className="tile__spark"><Sparkline values={spark} /></span>
        )}
      </span>
      <span aria-hidden="true" className="tile__foot">
        {stats
          ? <DeltaText delta={stats.delta} unit={unit} decimals={decimals} polarity={polarity} periodLabel={`sur ${rangeLabel}`} />
          : <span className="tile__none">Aucune mesure dans la plage</span>}
      </span>
    </button>
  )
})
