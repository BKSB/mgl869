import type { Route } from '../route'
import type { ConnectionStatus } from '../types'

const CONNECTION_LABEL: Record<ConnectionStatus, string> = {
  connecting: 'Connexion…',
  connected: 'WebSocket connecté',
  disconnected: 'WebSocket déconnecté',
}

interface Props {
  route: Route
  site: string
  alertsActive: number
  status: ConnectionStatus
}

export function Header({ route, site, alertsActive, status }: Props) {
  const link = (view: Route['view'], href: string, label: string, badge?: number) => (
    <a className={`nav-link${route.view === view ? ' is-active' : ''}`} href={href} aria-current={route.view === view ? 'page' : undefined}>
      {label}
      {badge ? <span className="badge-count">{badge}</span> : null}
    </a>
  )
  return (
    <header className="topbar">
      <a className="brand" href="#/rooms">
        <svg className="brand-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M3 11.5 12 4l9 7.5" />
          <path d="M5.5 10v9.5h13V10" />
          <path d="M10 19.5v-5h4v5" />
        </svg>
        <span className="brand-name">Jumeau numérique</span>
        {site && <span className="brand-site">/ {site}</span>}
      </a>
      <nav className="nav" aria-label="Vues">
        {link('rooms', '#/rooms', 'Par pièce')}
        {link('metric', '#/metrics', 'Par capteur')}
        {link('alerts', '#/alerts', 'Alertes', alertsActive)}
        <span className={`conn conn--${status}`} role="status">
          <span className="dot" />
          {CONNECTION_LABEL[status]}
        </span>
      </nav>
    </header>
  )
}
