import { AlertsChip } from './AlertsChip'
import { BrandMark } from './BrandMark'
import { HealthChip } from './HealthChip'
import { StatusBadge } from './StatusBadge'
import { ThemeToggle } from './ThemeToggle'
import type { AlertsApi } from '../hooks/useAlerts'
import type { HealthState } from '../hooks/useHealth'
import type { Alert, ConnectionStatus, HealthInfo, ThemeMode, TopicInfo } from '../types'

interface Props {
  /** Etat du flux du topic actif ; null = aucun flux a ecouter (liste de
   * topics vide ou en erreur) : le badge n'est pas rendu. */
  status: ConnectionStatus | null
  health: HealthInfo | null
  healthState: HealthState
  topics: TopicInfo[]
  alerts: AlertsApi
  /** « Voir » d'une alerte : topic selectionne, capteur isole. */
  onShowAlert: (alert: Alert) => void
  theme: ThemeMode
  onTheme: (m: ThemeMode) => void
}

/** Barre d'application opaque et collante : marque, etat du flux, sante,
 * alertes, bascule de theme. Aucun flou, aucun color-mix. */
export function AppBar({ status, health, healthState, topics, alerts, onShowAlert, theme, onTheme }: Props) {
  return (
    <header className="appbar">
      <div className="appbar__inner">
        <div className="appbar__brand">
          <BrandMark size={20} />
          <h1 className="appbar__name">gridd</h1>
          <span className="appbar__sub">Capteurs du campus · ÉTS Montréal</span>
        </div>
        <div className="appbar__status">
          {status && <StatusBadge status={status} />}
          <HealthChip health={health} state={healthState} topicsCount={topics.length} />
          <AlertsChip
            loaded={alerts.loaded} status={alerts.status} active={alerts.active}
            recent={alerts.recent} latest={alerts.latest} onShow={onShowAlert}
          />
          <ThemeToggle mode={theme} onChange={onTheme} />
        </div>
      </div>
    </header>
  )
}
