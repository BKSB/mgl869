import { Fragment } from 'react'
import type { Option, Status, Threshold } from '../types'

export function StatusBadge({ status, label }: { status: Status; label: string }) {
  return (
    <span className={`badge badge--${status}`}>
      <span className="dot" />
      {label}
    </span>
  )
}

/** « W > 1 000 ppm · E > 1 500 ppm », chaque seuil dans sa couleur ;
 * `short` : sans unite. */
export function Thresholds({ items, short = false }: { items: Threshold[]; short?: boolean }) {
  return (
    <span className="thresholds">
      {items.map((t, i) => (
        <Fragment key={i}>
          {i > 0 && ' · '}
          <span className={`text-${t.severity}`}>{short ? t.short : t.text}</span>
        </Fragment>
      ))}
    </span>
  )
}

interface SegmentedProps {
  options: Option[]
  value: string
  onChange: (id: string) => void
  label: string
}

export function Segmented({ options, value, onChange, label }: SegmentedProps) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          className={`segmented-item${o.id === value ? ' is-active' : ''}`}
          aria-pressed={o.id === value}
          onClick={() => onChange(o.id)}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function EmptyState({ text }: { text: string }) {
  return <p className="empty">{text}</p>
}
