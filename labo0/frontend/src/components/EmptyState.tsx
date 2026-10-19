import { Icon } from './Icon'
import type { IconName } from './Icon'
import { DISCONNECTED_TEXT, EMPTY_LABEL } from '../lib/stream'
import type { EmptyKind } from '../lib/stream'

type Kind = EmptyKind | 'empty-range' | 'api-error' | 'no-topics'

interface Props {
  kind: Kind
  onAction?: () => void
}

/** Memes mots que le sous-titre et les tiles (EMPTY_LABEL). */
const CONTENT: Record<Kind, { icon: IconName; title: string; desc?: string; action?: string }> = {
  connecting: { icon: 'loader', title: EMPTY_LABEL.connecting },
  replaying: { icon: 'clock', title: EMPTY_LABEL.replaying, desc: 'Les mesures arrivent par le flux temps réel.' },
  waiting: { icon: 'radio', title: 'En attente de données sur ce topic' },
  disconnected: { icon: 'alert-circle', title: DISCONNECTED_TEXT },
  'empty-range': {
    icon: 'clock', title: 'Aucune mesure dans la plage', desc: 'Élargissez la plage temporelle pour voir des données.',
    action: 'Afficher tout',
  },
  'api-error': {
    icon: 'x-circle', title: 'Impossible de charger la liste des topics', desc: 'Le backend ne répond pas sur /api/topics.',
    action: 'Réessayer',
  },
  'no-topics': {
    icon: 'radio', title: 'Aucun topic disponible', desc: 'Le backend ne publie aucun topic sur /api/topics.',
    action: 'Réessayer',
  },
}

export function EmptyState({ kind, onAction }: Props) {
  const { icon, title, desc, action } = CONTENT[kind]
  return (
    <div className="empty" role={kind === 'api-error' ? 'alert' : 'status'}>
      <span className="empty__icon"><Icon name={icon} size={24} /></span>
      <p className="empty__title">{title}</p>
      {desc && <p className="empty__desc">{desc}</p>}
      {action && onAction && (
        <button type="button" className="btn" onClick={onAction}>{action}</button>
      )}
    </div>
  )
}
