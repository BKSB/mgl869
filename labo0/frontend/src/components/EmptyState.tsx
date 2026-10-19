import { Icon } from './Icon'
import type { IconName } from './Icon'
import { DISCONNECTED_TEXT, EMPTY_LABEL } from '../lib/stream'
import type { EmptyKind } from '../lib/stream'

type Kind = EmptyKind | 'empty-range' | 'api-error' | 'no-topics'

interface Props {
  kind: Kind
  onRetry?: () => void
  onShowAll?: () => void
}

/** Etats du flux : memes mots que le sous-titre et les tiles (EMPTY_LABEL). */
const CONTENT: Record<Kind, { icon: IconName; title: string; desc?: string }> = {
  connecting: { icon: 'loader', title: EMPTY_LABEL.connecting },
  replaying: { icon: 'clock', title: EMPTY_LABEL.replaying, desc: 'Les mesures arrivent par le flux temps réel.' },
  waiting: { icon: 'radio', title: 'En attente de données sur ce topic' },
  disconnected: { icon: 'alert-circle', title: DISCONNECTED_TEXT },
  'empty-range': { icon: 'clock', title: 'Aucune mesure dans la plage', desc: 'Élargissez la plage temporelle pour voir des données.' },
  'api-error': { icon: 'x-circle', title: 'Impossible de charger la liste des topics', desc: 'Le backend ne répond pas sur /api/topics.' },
  'no-topics': { icon: 'radio', title: 'Aucun topic disponible', desc: 'Le backend ne publie aucun topic sur /api/topics.' },
}

/** Etat vide centre : disque 40 px, titre, description, action eventuelle.
 * Le parent conserve sa hauteur (le cadre ne saute pas). */
export function EmptyState({ kind, onRetry, onShowAll }: Props) {
  const { icon, title, desc } = CONTENT[kind]
  return (
    <div className="empty" role={kind === 'api-error' ? 'alert' : 'status'}>
      <span className="empty__icon"><Icon name={icon} size={24} /></span>
      <p className="empty__title">{title}</p>
      {desc && <p className="empty__desc">{desc}</p>}
      {kind === 'empty-range' && onShowAll && (
        <button type="button" className="btn" onClick={onShowAll}>Afficher tout</button>
      )}
      {(kind === 'api-error' || kind === 'no-topics') && onRetry && (
        <button type="button" className="btn" onClick={onRetry}>Réessayer</button>
      )}
    </div>
  )
}
