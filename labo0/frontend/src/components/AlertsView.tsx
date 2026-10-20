import { fmtTime } from '../format'
import { roomHash } from '../route'
import type { AlertsData } from '../types'
import { EmptyState, StatusBadge } from './StatusBadge'

interface Props {
  data: AlertsData | null
  onFilter: (id: string) => void
  onAck: (id: string) => void
}

export function AlertsView({ data, onFilter, onAck }: Props) {
  if (!data) return <EmptyState text="Chargement…" />
  return (
    <section className="content content--page">
      <h1 className="page-title">Alertes</h1>
      <p className="page-sub">
        {data.alerts_enabled ? `Reçues en temps réel par WebSocket · ${data.summary}` : 'Alertes désactivées côté backend (aucun fichier de règles).'}
      </p>
      <div className="pills" role="group" aria-label="Filtre">
        {data.filters.map((f) => (
          <button
            key={f.id}
            type="button"
            className={`pill${f.id === data.filter ? ' is-active' : ''}`}
            aria-pressed={f.id === data.filter}
            onClick={() => onFilter(f.id)}
          >
            {f.label}
            {f.count !== null && ` · ${f.count}`}
          </button>
        ))}
      </div>
      {data.alerts.length > 0 ? (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Sévérité</th>
                <th>Pièce</th>
                <th>Capteur</th>
                <th>Valeur</th>
                <th>Seuil atteint</th>
                <th>Déclenchée</th>
                <th>État</th>
                <th>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {data.alerts.map((a) => (
                <tr key={a.key} className={`row--${a.state}`}>
                  <td>
                    <StatusBadge status={a.severity} label={a.severity_label} />
                  </td>
                  <td className="cell-strong">{a.room.name}</td>
                  <td className="cell-muted">
                    {a.metric_label} · <code>{a.sensor_id}</code>
                  </td>
                  <td className={`mono text-${a.severity}`}>{a.value_text}</td>
                  <td className="mono cell-muted">{a.threshold_text}</td>
                  <td className="mono cell-muted">{fmtTime(a.since_ms)}</td>
                  <td>
                    {a.state_label}
                    {a.state_ms !== null && ` · ${fmtTime(a.state_ms)}`}
                  </td>
                  <td className="cell-actions">
                    {a.can_ack && (
                      <button type="button" className="btn" onClick={() => onAck(a.id)}>
                        Acquitter
                      </button>
                    )}
                    <a className="link" href={roomHash(a.room.id)}>
                      Voir la pièce
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState text="Aucune alerte." />
      )}
      <p className="footnote">
        Le déclenchement, la sévérité et la résolution sont décidés par le backend. « Acquitter » envoie seulement l’action au backend.
      </p>
    </section>
  )
}
