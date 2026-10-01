import type { ConnectionStatus } from '../types'

const STATUS_TEXT: Record<ConnectionStatus, string> = {
  live: 'En direct',
  connecting: 'Connexion…',
  disconnected: 'Déconnecté — reconnexion…',
}

/** Indicateur d'etat de la connexion WebSocket. */
export function StatusBadge({ status }: { status: ConnectionStatus }) {
  return <span className={`status status-${status}`}>{STATUS_TEXT[status]}</span>
}
