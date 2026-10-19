import type { CSSProperties } from 'react'
import { PlaceholderTile, StatTile } from './StatTile'
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
  selected: string | null
  hovered: string | null
  alerts: Record<string, Alert>
  emptyKind: EmptyKind | null
  onToggle: (id: string) => void
  onHover: (id: string | null) => void
}

const PLACEHOLDERS = [0, 1, 2, 3]

/** px ; GAP = gap de .tiles. Sous 720 px, le CSS impose 2 colonnes. */
const TILE_MIN = 200
const GAP = 12

/** Rangees equilibrees, jamais d'orpheline (6 -> 3 + 3, 7 -> 4 + 3) ; une seule
 * rangee : au moins 4 colonnes (pas de tiles geantes). */
function columnsFor(count: number, width: number): number {
  if (width <= 0) return Math.max(4, count) // largeur pas encore mesuree
  const fit = Math.max(1, Math.floor((width + GAP) / (TILE_MIN + GAP)))
  if (count <= fit) return Math.min(fit, Math.max(4, count))
  const rows = Math.ceil(count / fit)
  return Math.ceil(count / rows)
}

const gridStyle = (cols: number) => ({ '--cols': cols }) as CSSProperties

/** Sans capteur connu : 4 tiles fantomes, le cadre ne saute pas au changement de topic. */
export function StatTileRow({
  sensorIds, sensors, names, slots, byId, unit, decimals, polarity, rangeLabel,
  selected, hovered, alerts, emptyKind, onToggle, onHover,
}: Props) {
  const [gridRef, { width }] = useElementSize<HTMLElement>()
  if (sensorIds.length === 0) {
    const text = EMPTY_LABEL[emptyKind ?? 'connecting']
    return (
      <section ref={gridRef} className="tiles" aria-label="Dernières mesures par capteur" style={gridStyle(columnsFor(PLACEHOLDERS.length, width))}>
        {PLACEHOLDERS.map((i) => <PlaceholderTile key={i} text={text} />)}
      </section>
    )
  }
  return (
    <section ref={gridRef} className="tiles" aria-label="Dernières mesures par capteur" style={gridStyle(columnsFor(sensorIds.length, width))}>
      {sensorIds.map((id) => (
        <StatTile
          key={id}
          id={id}
          name={names[id]}
          slot={slots[id]}
          unit={sensors[id]?.last.unit ?? unit}
          decimals={decimals}
          stats={byId[id]?.stats ?? null}
          spark={byId[id]?.spark ?? []}
          polarity={polarity}
          rangeLabel={rangeLabel}
          active={selected === id}
          dimmed={selected !== null && selected !== id}
          hovered={hovered === id}
          alert={alerts[id]}
          onToggle={onToggle}
          onHover={onHover}
        />
      ))}
    </section>
  )
}
