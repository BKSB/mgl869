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

/** Fraicheur d'un capteur : icone coloree + libelle + age. Le texte reste en
 * encre secondaire. En mode compact, « À jour » passe en sr-only (l'icone
 * verte suffit) mais « Retard » / « Muet » restent visibles : l'icone ambre
 * n'atteint pas 3:1 sur fond clair et ne peut pas porter l'alerte seule. Les
 * espaces entre les spans gardent un texte accessible lisible (« À jour ·
 * il y a 5 s ») ; ils ne comptent pas dans la mise en page flex. */
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
