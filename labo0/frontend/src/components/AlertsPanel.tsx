import { Icon } from './Icon'
import { SeverityIcon } from './SeverityIcon'
import { useNow } from '../hooks/useNow'
import { alertPlace, alertText, eventKey, eventLabel, eventText, SEVERITY_LABEL } from '../lib/alerts'
import { fmtAge, fmtDateTime, fmtDayTime, fmtTime } from '../lib/format'
import { topicLabel } from '../lib/metrics'
import { RECONNECT_TEXT } from '../lib/stream'
import { DAY } from '../lib/time'
import type { Alert, AlertEvent, AlertsStatus } from '../types'

const RECENT_SHOWN = 10

interface Props {
  titleId: string
  /** GET /api/alerts a repondu ; sinon etat inconnu, jamais « Aucune alerte ». */
  loaded: boolean
  status: AlertsStatus
  active: Alert[]
  recent: AlertEvent[]
  onShow: (alert: Alert) => void
  onClose: () => void
}

const startLabel = (t: number, now: number) => (now - t > DAY ? fmtDayTime(t) : fmtTime(t, false))

function ActiveRow({ alert, now, onShow }: { alert: Alert; now: number; onShow: (a: Alert) => void }) {
  const topic = topicLabel(alert.topic)
  const place = alertPlace(alert)
  return (
    <li className="alert-row">
      <SeverityIcon severity={alert.severity} size={16} className="alert-row__icon" />
      <div className="alert-row__main">
        <p className="alert-row__title">
          <strong>{SEVERITY_LABEL[alert.severity]}</strong>
          <span className="alert-row__ctx"> · {topic} · <span className="nowrap">{place}</span></span>
        </p>
        <p className="alert-row__msg">{alertText(alert)}</p>
        <p className="alert-row__meta" title={fmtDateTime(alert.since_ms)}>
          Depuis {startLabel(alert.since_ms, now)} · {fmtAge(now - alert.since_ms)}
        </p>
      </div>
      <button
        type="button"
        className="btn btn--sm alert-row__show"
        aria-label={`Voir ${topic}, ${place}`}
        title="Afficher ce topic et isoler le capteur"
        onClick={() => onShow(alert)}
      >
        Voir
      </button>
    </li>
  )
}

function eventIcon(e: AlertEvent) {
  if (e.kind === 'resolved') return <Icon name="check-circle" size={14} className="sev sev--good" />
  if (e.kind === 'escalated') return <SeverityIcon severity="critical" />
  if (e.kind === 'deescalated') return <SeverityIcon severity="warning" />
  return <SeverityIcon severity={e.alert.severity} />
}

function RecentRow({ event, now }: { event: AlertEvent; now: number }) {
  return (
    <li className="event-row">
      <span className="event-row__icon">{eventIcon(event)}</span>
      <div className="event-row__main">
        <p className="event-row__title">
          <strong>{eventLabel(event.kind, event.alert.severity)}</strong>
          {/* Pas de topic : eventText le nomme deja */}
          <span className="event-row__ctx"> · <span className="nowrap">{alertPlace(event.alert)}</span></span>
        </p>
        <p className="event-row__msg">{eventText(event)}</p>
      </div>
      <time className="event-row__time" dateTime={new Date(event.at_ms).toISOString()} title={fmtDateTime(event.at_ms)}>
        {fmtAge(now - event.at_ms)}
      </time>
    </li>
  )
}

/** Monte panneau ouvert seulement : useNow (ages, toutes les 5 s) ne tourne pas sinon. */
export function AlertsPanel({ titleId, loaded, status, active, recent, onShow, onClose }: Props) {
  const now = useNow()
  const disabled = status === 'disabled'
  const known = loaded && !disabled
  const shown = recent.slice(0, RECENT_SHOWN)
  return (
    <>
      <div className="alerts-panel__head">
        <h2 id={titleId} className="alerts-panel__title">
          {known ? `Alertes actives (${active.length})` : 'Alertes'}
        </h2>
        <button type="button" className="icon-btn" aria-label="Fermer" title="Fermer (Échap)" onClick={onClose}>
          <Icon name="x" size={16} />
        </button>
      </div>
      <div className="alerts-panel__body">
        {status === 'disconnected' && (
          <p className="alerts-panel__note">
            <Icon name="alert-circle" size={14} className="sev sev--critical" />
            <span>
              {loaded
                ? `Flux des alertes interrompu — ${RECONNECT_TEXT}. Dernier état connu affiché.`
                : `Service des alertes injoignable — ${RECONNECT_TEXT}.`}
            </span>
          </p>
        )}
        {disabled ? (
          <div className="alerts-empty">
            <span className="alerts-empty__icon"><Icon name="bell-off" size={16} /></span>
            <p className="alerts-empty__title">Alertes désactivées</p>
            <p className="alerts-empty__desc">Le service ne charge aucune règle d’alerte (fichier config/alerts.yaml absent).</p>
          </div>
        ) : !loaded ? (
          <div className="alerts-empty">
            <span className="alerts-empty__icon"><Icon name="clock" size={16} /></span>
            <p className="alerts-empty__title">État des alertes inconnu</p>
            <p className="alerts-empty__desc">En attente d’une réponse du service des alertes.</p>
          </div>
        ) : active.length === 0 ? (
          <div className="alerts-empty">
            <span className="alerts-empty__icon"><Icon name="check-circle" size={16} className="sev sev--good" /></span>
            <p className="alerts-empty__title">Aucune alerte active</p>
            <p className="alerts-empty__desc">Toutes les mesures respectent les seuils configurés.</p>
          </div>
        ) : (
          <ul className="alerts-list" aria-label="Alertes actives">
            {active.map((a) => <ActiveRow key={a.id} alert={a} now={now} onShow={onShow} />)}
          </ul>
        )}
        {known && (
          <section className="alerts-recent" aria-labelledby={`${titleId}-recent`}>
            <h3 id={`${titleId}-recent`} className="alerts-recent__title">Récemment</h3>
            {shown.length === 0 ? (
              <p className="alerts-recent__none">Aucun événement récent.</p>
            ) : (
              <ul className="alerts-recent__list">
                {shown.map((e) => <RecentRow key={eventKey(e)} event={e} now={now} />)}
              </ul>
            )}
          </section>
        )}
      </div>
    </>
  )
}
