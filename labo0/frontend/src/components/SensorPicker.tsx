interface Props {
  sensorIds: string[]
  selected: string | 'all'
  colorSlots: Record<string, number>
  names: Record<string, string>
  onSelect: (sensor: string | 'all') => void
}

/** Rangee de selection du capteur : « Tous » ou un capteur precis. */
export function SensorPicker({ sensorIds, selected, colorSlots, names, onSelect }: Props) {
  return (
    <nav className="sensor-picker" aria-label="Choix du capteur">
      <button
        className={selected === 'all' ? 'active' : ''}
        onClick={() => onSelect('all')}
      >
        Tous
      </button>
      {sensorIds.map((id) => (
        <button
          key={id}
          className={selected === id ? 'active' : ''}
          onClick={() => onSelect(id)}
        >
          <span
            className="dot"
            style={{ background: `var(--series-${colorSlots[id]})` }}
            aria-hidden
          />
          {names[id]}
        </button>
      ))}
    </nav>
  )
}
