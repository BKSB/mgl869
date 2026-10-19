import { Icon } from './Icon'
import type { IconName } from './Icon'
import { RECONNECT_TEXT } from '../lib/stream'
import type { ConnectionStatus } from '../types'

const STATUS: Record<ConnectionStatus, { label: string; icon: IconName; tone: string }> = {
  live: { label: 'En direct', icon: 'radio', tone: 'good' },
  connecting: { label: 'Connexion…', icon: 'loader', tone: 'warning' },
  disconnected: { label: `Déconnecté · ${RECONNECT_TEXT}`, icon: 'alert-circle', tone: 'critical' },
}

/** Etat du flux WebSocket du topic actif : couleur + icone + libelle. Le
 * libelle est masque visuellement (sr-only) sous 720 px mais reste le contenu
 * de la region live : un changement d'etat est toujours annonce (une coupure
 * une seule fois : l'etat ne change pas a chaque tentative). */
export function StatusBadge({ status }: { status: ConnectionStatus }) {
  const { label, icon, tone } = STATUS[status]
  return (
    <span role="status" aria-live="polite" className={`badge badge--${tone}`}>
      <Icon name={icon} size={14} className={status === 'connecting' ? 'badge__icon icon--spin' : 'badge__icon'} />
      <span className="badge__label">{label}</span>
    </span>
  )
}
