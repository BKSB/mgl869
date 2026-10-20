import { fmtAgo, fmtTime } from '../format'
import { roomHash } from '../route'
import type { Toast } from '../types'

interface Props {
  toasts: Toast[]
  now: number
  onDismiss: (id: string) => void
  onAck: (alertId: string) => void
}

/** Notifications envoyees par le backend (alerte declenchee ou escaladee). */
export function Toasts({ toasts, now, onDismiss, onAck }: Props) {
  return (
    <div className="toasts" role="region" aria-live="polite" aria-label="Notifications">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast--${t.severity}`}>
          <div className="toast-head">
            <span className={`toast-sev text-${t.severity}`}>
              <svg viewBox="0 0 16 16" aria-hidden="true">
                <circle cx="8" cy="8" r="6.5" />
                <path d="M8 4.5v4M8 11v.5" />
              </svg>
              {t.severity_label.toUpperCase()}
            </span>
            <span className="toast-time">
              {fmtTime(t.at_ms)} · {fmtAgo(t.at_ms, now)}
            </span>
            <button type="button" className="toast-close" aria-label="Fermer" onClick={() => onDismiss(t.id)}>
              ×
            </button>
          </div>
          <div className="toast-title">{t.title}</div>
          <div className="toast-text">
            <span className={`mono text-${t.severity}`}>{t.value_text}</span> {t.text}
          </div>
          <div className="toast-actions">
            <a className={`btn btn--${t.severity}`} href={roomHash(t.room_id)} onClick={() => onDismiss(t.id)}>
              Voir la pièce
            </a>
            <button
              type="button"
              className="btn"
              onClick={() => {
                onAck(t.alert_id)
                onDismiss(t.id)
              }}
            >
              Acquitter
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}
