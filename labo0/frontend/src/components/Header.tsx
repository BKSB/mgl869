import { fmtAgo } from '../format'
import type { Route } from '../route'
import type { ConnectionStatus, People } from '../types'

const CONNECTION_LABEL: Record<ConnectionStatus, string> = {
  connecting: 'Connexion…',
  connected: 'connecté',
  disconnected: 'déconnecté',
}

interface Props {
  route: Route
  site: string
  people: People | null
  alertsActive: number
  status: ConnectionStatus
  now: number
}

export function Header({ route, site, people, alertsActive, status, now }: Props) {
  const link = (view: Route['view'], href: string, label: string, badge?: number) => (
    <a className={`nav-link${route.view === view ? ' is-active' : ''}`} href={href} aria-current={route.view === view ? 'page' : undefined}>
      {label}
      {badge ? <span className="badge-count">{badge}</span> : null}
    </a>
  )
  return (
    <header className="topbar">
      <div className="topbar-left">
        <a className="brand" href="#/rooms">
          <svg className="brand-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M3 11.5 12 4l9 7.5" />
            <path d="M5.5 10v9.5h13V10" />
            <path d="M10 19.5v-5h4v5" />
          </svg>
          <span className="brand-name">Jumeau numérique</span>
          {site && <span className="brand-site">/ {site}</span>}
        </a>
        {people && (
          <span className="people" role="status">
            <svg className="people-icon" viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="9" cy="8" r="3.2" />
              <path d="M3.5 19c0-3.2 2.5-5.2 5.5-5.2s5.5 2 5.5 5.2" />
              <circle cx="17" cy="9" r="2.6" />
              <path d="M15.6 14.4c2.9 0 4.9 1.9 4.9 4.6" />
            </svg>
            <strong className="people-count">{people.count_text}</strong>
            <span className="people-label">
              {people.label} · {fmtAgo(people.updated_ms, now)}
            </span>
          </span>
        )}
      </div>
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
