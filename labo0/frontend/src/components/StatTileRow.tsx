import type { CSSProperties } from 'react'
import { StatTile } from './StatTile'
import { useElementSize } from '../hooks/useElementSize'
import type { SensorDerived } from '../hooks/useSeriesStats'
import { EMPTY_LABEL } from '../lib/stream'
import type { EmptyKind } from '../lib/stream'
import type { Alert, Polarity, SensorSeries } from '../types'

interface Props {
  sensorIds: string[]
  sensors: Record<string, SensorSeries>
  names: Record<string, string>
  slots: Record<string, number>
  byId: Record<string, SensorDerived>
  unit: string
  decimals: number
  polarity: Polarity
  rangeLabel: string
  selected: string | 'all'
  hovered: string | null
  /** Alertes actives du topic par node_id. */
  alerts: Record<string, Alert>
  /** Raison de l'etat vide (calculee par App, comme le sous-titre et le
   * corps de la carte) : texte des tiles fantomes. */
  emptyKind: EmptyKind | null
  onToggle: (id: string) => void
  onHover: (id: string | null) => void
}

const PLACEHOLDERS = [0, 1, 2, 3]

/** Largeur minimale d'une tile et gouttiere de la grille (px, >= 720 px ;
 * en dessous, le CSS impose 2 colonnes et etire une derniere tile impaire
 * sur toute la rangee). */
const TILE_MIN = 200
const GAP = 12

/** Colonnes de la grille, equilibrees : jamais de tile orpheline (5 + 1,
 * 4 + 2) quand les capteurs ne tiennent pas sur une rangee. Une rangee : un
 * capteur par colonne, au moins 4 colonnes (pas de tiles geantes a 1 ou 2
 * capteurs). Plusieurs rangees : le minimum de rangees, puis le minimum de
 * colonnes pour ce nombre de rangees (6 -> 3 + 3, 7 -> 4 + 3, 5 -> 3 + 2).
 * Chaque tile garde au moins TILE_MIN px. */
function columnsFor(count: number, width: number): number {
  if (width <= 0) return Math.max(4, count) // avant la premiere mesure
  const fit = Math.max(1, Math.floor((width + GAP) / (TILE_MIN + GAP)))
  if (count <= fit) return Math.min(fit, Math.max(4, count))
  const rows = Math.ceil(count / fit)
  return Math.ceil(count / rows)
}

const gridStyle = (cols: number) => ({ '--cols': cols }) as CSSProperties

/** Rangee de tiles ; quatre tiles stables « — » tant qu'aucun capteur n'est
 * connu (le cadre ne saute pas au changement de topic). Leur texte est
 * visuel seulement : l'etat vide de la carte l'annonce deja (role status). */
export function StatTileRow({
  sensorIds, sensors, names, slots, byId, unit, decimals, polarity, rangeLabel,
  selected, hovered, alerts, emptyKind, onToggle, onHover,
}: Props) {
  const [gridRef, { width }] = useElementSize<HTMLElement>()
  if (sensorIds.length === 0) {
    const text = EMPTY_LABEL[emptyKind ?? 'connecting']
    return (
      <section ref={gridRef} className="tiles" aria-label="Dernières mesures par capteur" style={gridStyle(columnsFor(PLACEHOLDERS.length, width))}>
        {PLACEHOLDERS.map((i) => (
          <div key={i} className="tile tile--placeholder" aria-hidden="true">
            <span className="tile__head">
              <span className="tile__label"><span className="key" style={{ background: 'var(--baseline)' }} /><span className="tile__name">Capteur</span></span>
              <span className="tile__id">—</span>
            </span>
            <span className="tile__body"><span className="tile__value">—</span></span>
            <span className="tile__foot"><span className="tile__none">{text}</span></span>
          </div>
        ))}
      </section>
    )
  }
  return (
    <section ref={gridRef} className="tiles" aria-label="Dernières mesures par capteur" style={gridStyle(columnsFor(sensorIds.length, width))}>
      {sensorIds.map((id) => (
        <StatTile
          key={id}
          id={id}
          name={names[id] ?? id}
          slot={slots[id] ?? 1}
          unit={sensors[id]?.last.unit ?? unit}
          decimals={decimals}
          stats={byId[id]?.stats ?? null}
          spark={byId[id]?.spark ?? []}
          polarity={polarity}
          rangeLabel={rangeLabel}
          active={selected === id}
          dimmed={selected !== 'all' && selected !== id}
          hovered={hovered === id}
          alert={alerts[id]}
          onToggle={onToggle}
          onHover={onHover}
        />
      ))}
    </section>
  )
}
