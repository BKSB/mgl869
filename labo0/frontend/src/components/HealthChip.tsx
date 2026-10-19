import { Icon } from './Icon'
import type { IconName } from './Icon'
import { topicLabel } from '../lib/labels'
import type { HealthState } from '../hooks/useHealth'
import type { HealthInfo } from '../types'

interface Props {
  health: HealthInfo | null
  state: HealthState
  topicsCount: number
}

const ICONS: Record<HealthState, { icon: IconName; tone: string }> = {
  pending: { icon: 'clock', tone: 'muted' },
  ok: { icon: 'check-circle', tone: 'good' },
  degraded: { icon: 'alert-triangle', tone: 'warning' },
  unreachable: { icon: 'x-circle', tone: 'critical' },
}

/** Sante du service (GET /health) : jamais masque, derniere valeur conservee.
 * role=status (meme anatomie que StatusBadge) : le libelle reste du texte,
 * masque visuellement seulement sous 720 px, donc toujours le nom lu. */
export function HealthChip({ health, state, topicsCount }: Props) {
  const consumers = health?.consumers ?? {}
  const up = Object.values(consumers).filter(Boolean).length
  const total = topicsCount || Object.keys(consumers).length
  const counter = health ? ` · ${up}/${total}` : ''
  const label =
    state === 'pending' ? 'Service : …'
    : state === 'ok' ? `Service : OK${counter}`
    : state === 'degraded' ? `Service : dégradé${counter}`
    : `Service : injoignable${counter}`
  const down = Object.entries(consumers).filter(([, ok]) => !ok).map(([name]) => topicLabel(name))
  const title = down.length > 0 ? `Consommateurs arrêtés : ${down.join(', ')}` : undefined
  const { icon, tone } = ICONS[state]
  return (
    <span role="status" className={`badge badge--${tone}`} title={title}>
      <Icon name={icon} size={14} className="badge__icon" />
      <span className="badge__label">{label}</span>
    </span>
  )
}
