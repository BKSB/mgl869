import { useRef } from 'react'
import type { KeyboardEvent } from 'react'
import { Icon } from './Icon'
import { useMediaQuery } from '../hooks/useMediaQuery'

interface Props {
  sensorIds: string[]
  names: Record<string, string>
  slots: Record<string, number>
  selected: string | 'all'
  onSelect: (s: string | 'all') => void
  grow?: boolean
  disabled?: boolean
}

/** Filtre de capteur : pills radio >= 900 px, <select> natif en dessous.
 * Une seule forme est rendue a la fois. */
export function SensorFilter({ sensorIds, names, slots, selected, onSelect, grow, disabled = false }: Props) {
  const wide = useMediaQuery('(min-width: 900px)')
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const values: (string | 'all')[] = ['all', ...sensorIds]
  // Nom complet au survol : la pastille peut etre tronquee pour tenir sur une rangee
  const chipTitle = (id: string) => {
    const name = names[id] ?? id
    return name.includes(id) ? name : `${name} — ${id}`
  }

  if (!wide) {
    return (
      <div className={`select-wrap${grow ? '' : ' select-wrap--auto'}`} aria-disabled={disabled || undefined}>
        <label className="sr-only" htmlFor="sensor-select">Capteur</label>
        <select
          id="sensor-select"
          className="select"
          value={selected}
          disabled={disabled}
          onChange={(e) => onSelect(e.target.value === 'all' ? 'all' : e.target.value)}
        >
          <option value="all">Tous les capteurs ({sensorIds.length})</option>
          {sensorIds.map((id) => (
            <option key={id} value={id}>{names[id] ?? id} — {id}</option>
          ))}
        </select>
        <Icon name="chevron-down" size={16} />
      </div>
    )
  }

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const n = values.length
    let next: number
    switch (e.key) {
      case 'ArrowLeft': case 'ArrowUp': next = (i - 1 + n) % n; break
      case 'ArrowRight': case 'ArrowDown': next = (i + 1) % n; break
      case 'Home': next = 0; break
      case 'End': next = n - 1; break
      default: return
    }
    e.preventDefault()
    onSelect(values[next])
    refs.current[next]?.focus()
  }

  return (
    <div role="radiogroup" aria-label="Capteur" className="chips" aria-disabled={disabled || undefined}>
      {values.map((v, i) => {
        const checked = v === selected
        return (
          <button
            key={v}
            ref={(el) => { refs.current[i] = el }}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={checked ? 0 : -1}
            disabled={disabled}
            className="chip"
            title={v === 'all' ? undefined : chipTitle(v)}
            onClick={() => onSelect(v)}
            onKeyDown={(e) => onKeyDown(e, i)}
          >
            {v !== 'all' && (
              <span className="chip__dot" style={{ background: `var(--series-${slots[v] ?? 1})` }} aria-hidden="true" />
            )}
            <span className="chip__label">{v === 'all' ? 'Tous' : names[v] ?? v}</span>
          </button>
        )
      })}
    </div>
  )
}
