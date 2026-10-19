import { useRef } from 'react'
import type { KeyboardEvent } from 'react'
import { Icon } from './Icon'
import { useMediaQuery } from '../hooks/useMediaQuery'
import { rovingIndex } from '../lib/roving'

interface Props {
  sensorIds: string[]
  names: Record<string, string>
  slots: Record<string, number>
  selected: string | null
  onSelect: (s: string | null) => void
  grow?: boolean
  disabled?: boolean
}

export function SensorFilter({ sensorIds, names, slots, selected, onSelect, grow, disabled = false }: Props) {
  const wide = useMediaQuery('(min-width: 900px)')
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const values: (string | null)[] = [null, ...sensorIds]
  // La pastille peut etre tronquee : nom complet (et id) au survol
  const chipTitle = (id: string) => (names[id].includes(id) ? names[id] : `${names[id]} — ${id}`)

  if (!wide) {
    return (
      <div className={`select-wrap${grow ? '' : ' select-wrap--auto'}`} aria-disabled={disabled || undefined}>
        <label className="sr-only" htmlFor="sensor-select">Capteur</label>
        {/* '' : tous les capteurs (un sensor_id n'est jamais vide) */}
        <select
          id="sensor-select"
          className="select"
          value={selected ?? ''}
          disabled={disabled}
          onChange={(e) => onSelect(e.target.value || null)}
        >
          <option value="">Tous les capteurs ({sensorIds.length})</option>
          {sensorIds.map((id) => (
            <option key={id} value={id}>{names[id]} — {id}</option>
          ))}
        </select>
        <Icon name="chevron-down" size={16} />
      </div>
    )
  }

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const next = rovingIndex(e.key, i, values.length)
    if (next === null) return
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
            key={v ?? ''}
            ref={(el) => { refs.current[i] = el }}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={checked ? 0 : -1}
            disabled={disabled}
            className="chip"
            title={v === null ? undefined : chipTitle(v)}
            onClick={() => onSelect(v)}
            onKeyDown={(e) => onKeyDown(e, i)}
          >
            {v !== null && (
              <span className="chip__dot" style={{ background: `var(--series-${slots[v]})` }} aria-hidden="true" />
            )}
            <span className="chip__label">{v === null ? 'Tous' : names[v]}</span>
          </button>
        )
      })}
    </div>
  )
}
