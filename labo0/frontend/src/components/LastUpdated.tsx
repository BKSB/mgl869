import { Icon } from './Icon'
import { useNow } from '../hooks/useNow'
import { fmtAge, fmtDateTime } from '../lib/format'
import { freshness } from '../lib/stats'

interface Props {
  t: number | undefined
  period: number
}

/** En retard : horloge en plus du point ambre, la couleur ne porte pas le sens seule. */
export function LastUpdated({ t, period }: Props) {
  const now = useNow()
  if (t === undefined) return <span className="updated">—</span>
  const fresh = freshness(now - t, period) === 'fresh'
  return (
    <span className={fresh ? 'updated updated--fresh' : 'updated updated--late'} title={fmtDateTime(t)}>
      <span className="updated__dot" aria-hidden="true" />
      {!fresh && <Icon name="clock" size={12} />}
      <span>Mis à jour {fmtAge(now - t)}</span>
    </span>
  )
}
