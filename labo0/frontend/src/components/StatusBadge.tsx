import { Icon } from './Icon'
import type { IconName } from './Icon'
import { RECONNECT_TEXT } from '../lib/stream'
import type { ConnectionStatus, Tone } from '../types'

const STATUS: Record<ConnectionStatus, { label: string; icon: IconName; tone: Tone }> = {
  live: { label: 'En direct', icon: 'radio', tone: 'good' },
  connecting: { label: 'Connexion…', icon: 'loader', tone: 'warning' },
  disconnected: { label: `Déconnecté · ${RECONNECT_TEXT}`, icon: 'alert-circle', tone: 'critical' },
}

/** Libelle toujours rendu (contenu de la region live), masque en CSS sous 720 px. */
export function StatusBadge({ status }: { status: ConnectionStatus }) {
  const { label, icon, tone } = STATUS[status]
  return (
    <span role="status" aria-live="polite" className={`badge badge--${tone}`}>
      <Icon name={icon} size={14} className={status === 'connecting' ? 'badge__icon icon--spin' : 'badge__icon'} />
      <span className="badge__label">{label}</span>
    </span>
  )
}
