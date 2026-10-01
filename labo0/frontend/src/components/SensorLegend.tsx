import type { SensorSeries } from '../types'

interface Props {
  /** Capteurs affiches sur le graphe, dans l'ordre. */
  sensorIds: string[]
  sensors: Record<string, SensorSeries>
  colorSlots: Record<string, number>
  names: Record<string, string>
}

/** Legende sous le graphe : pastille, nom, derniere valeur et node_id. */
export function SensorLegend({ sensorIds, sensors, colorSlots, names }: Props) {
  return (
    <ul className="legend" aria-label="Dernières valeurs">
      {sensorIds.map((id) => (
        <li key={id}>
          <span
            className="dot"
            style={{ background: `var(--series-${colorSlots[id]})` }}
            aria-hidden
          />
          <span className="legend-id">{names[id]}</span>
          <strong>
            {sensors[id].last.value?.toLocaleString('fr-CA')}
            {sensors[id].last.unit && ` ${sensors[id].last.unit}`}
          </strong>
          <span className="legend-zone">{id}</span>
        </li>
      ))}
    </ul>
  )
}
