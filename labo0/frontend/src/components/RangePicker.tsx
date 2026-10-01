/** Fenetre temporelle affichee, en millisecondes ('all' = tout l'historique). */
export type TimeRange = number | 'all'

const PRESETS: { label: string; value: TimeRange }[] = [
  { label: '15 min', value: 15 * 60_000 },
  { label: '1 h', value: 60 * 60_000 },
  { label: '3 h', value: 3 * 60 * 60_000 },
  { label: 'Tout', value: 'all' },
]

interface Props {
  selected: TimeRange
  onSelect: (range: TimeRange) => void
}

/** Preselections de plage temporelle (fenetre glissante sur le graphe). */
export function RangePicker({ selected, onSelect }: Props) {
  return (
    <nav className="range-picker" aria-label="Plage temporelle">
      {PRESETS.map(({ label, value }) => (
        <button
          key={label}
          className={value === selected ? 'active' : ''}
          onClick={() => onSelect(value)}
        >
          {label}
        </button>
      ))}
    </nav>
  )
}
