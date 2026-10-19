import { Icon } from './Icon'
import type { IconName } from './Icon'
import { fmtAge, fmtDateTime } from '../lib/format'
import { freshness } from '../lib/stats'
import type { Freshness } from '../types'

interface Props {
  lastT: number | undefined
  period: number
  now: number
  compact?: boolean
}

const LEVELS: Record<Freshness, { icon: IconName; label: string; short: string }> = {
  fresh: { icon: 'check-circle', label: 'À jour', short: 'À jour' },
  late: { icon: 'alert-triangle', label: 'En retard', short: 'Retard' },
  stale: { icon: 'x-circle', label: 'Muet', short: 'Muet' },
}

/** Compact : libelle en sr-only si frais seulement (l'icone ambre n'atteint pas
 * 3:1 sur fond clair). Les {' '} gardent un texte accessible lisible. */
export function FreshnessBadge({ lastT, period, now, compact = false }: Props) {
  if (lastT === undefined) return <span className="fresh">—</span>
  const level = freshness(now - lastT, period)
  const { icon, label, short } = LEVELS[level]
  return (
    <span className={`fresh fresh--${level}`} title={fmtDateTime(lastT)}>
      <Icon name={icon} size={14} />
      {compact && level === 'fresh' ? (
        <span className="sr-only">{label} · </span>
      ) : (
        <>
          <span>{compact ? short : label}</span>{' '}
          <span aria-hidden="true">·</span>{' '}
        </>
      )}
      <span>{fmtAge(now - lastT)}</span>
    </span>
  )
}
