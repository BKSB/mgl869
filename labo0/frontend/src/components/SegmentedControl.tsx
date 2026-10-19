import { useRef } from 'react'
import type { KeyboardEvent } from 'react'
import { Icon } from './Icon'
import type { IconName } from './Icon'
import { rovingIndex } from '../lib/roving'

export interface SegmentOption<T extends string | number> {
  value: T
  label: string
  icon?: IconName
  title?: string
  iconOnly?: boolean
}

interface Props<T extends string | number> {
  options: SegmentOption<T>[]
  value: T
  onChange: (v: T) => void
  ariaLabel: string
  size?: 'sm' | 'md'
  grow?: boolean
  showCheck?: boolean
  disabled?: boolean
}

/** `disabled` sur chaque bouton : le CSS du groupe ne bloque que la souris. */
export function SegmentedControl<T extends string | number>({
  options, value, onChange, ariaLabel, size = 'md', grow = false, showCheck = false, disabled = false,
}: Props<T>) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const next = rovingIndex(e.key, i, options.length)
    if (next === null) return
    e.preventDefault()
    onChange(options[next].value)
    refs.current[next]?.focus()
  }

  const cls = ['seg', `seg--${size}`, grow ? 'seg--grow' : ''].filter(Boolean).join(' ')
  return (
    <div role="radiogroup" aria-label={ariaLabel} className={cls} aria-disabled={disabled || undefined}>
      {options.map((opt, i) => {
        const checked = opt.value === value
        return (
          <button
            key={opt.value}
            ref={(el) => { refs.current[i] = el }}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={checked ? 0 : -1}
            title={opt.title}
            disabled={disabled}
            className={opt.iconOnly ? 'seg__btn seg__btn--icon' : 'seg__btn'}
            onClick={() => onChange(opt.value)}
            onKeyDown={(e) => onKeyDown(e, i)}
          >
            {showCheck && checked && <Icon name="check" size={16} className="seg__check" />}
            {opt.icon && <Icon name={opt.icon} size={14} />}
            <span className={opt.iconOnly ? 'sr-only' : undefined}>{opt.label}</span>
          </button>
        )
      })}
    </div>
  )
}
