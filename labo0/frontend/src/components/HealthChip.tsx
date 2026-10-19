import { Icon } from './Icon'
import type { IconName } from './Icon'
import { topicLabel } from '../lib/metrics'
import type { HealthState } from '../hooks/useHealth'
import type { HealthInfo, Tone } from '../types'

interface Props {
  health: HealthInfo | null
  state: HealthState
  topicsCount: number
}

const STATES: Record<HealthState, { icon: IconName; tone: Tone; text: string }> = {
  pending: { icon: 'clock', tone: 'muted', text: '…' },
  ok: { icon: 'check-circle', tone: 'good', text: 'OK' },
  degraded: { icon: 'alert-triangle', tone: 'warning', text: 'dégradé' },
  unreachable: { icon: 'x-circle', tone: 'critical', text: 'injoignable' },
}

export function HealthChip({ health, state, topicsCount }: Props) {
  const consumers = health?.consumers ?? {}
  const up = Object.values(consumers).filter(Boolean).length
  const total = topicsCount || Object.keys(consumers).length
  const counter = health ? ` · ${up}/${total}` : ''
  const { icon, tone, text } = STATES[state]
  const down = Object.entries(consumers).filter(([, ok]) => !ok).map(([name]) => topicLabel(name))
  const title = down.length > 0 ? `Consommateurs arrêtés : ${down.join(', ')}` : undefined
  return (
    <span role="status" className={`badge badge--${tone}`} title={title}>
      <Icon name={icon} size={14} className="badge__icon" />
      <span className="badge__label">{`Service : ${text}${counter}`}</span>
    </span>
  )
}
