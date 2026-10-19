/** Message Kafka tel que diffuse par le backend sur /ws/<topic>. */
export interface TopicRecord {
  topic: string
  partition: number
  offset: number
  timestamp_ms: number
  key: string | null
  value: SensorValue | string | null
  /** Identifiant du capteur calcule par le backend (node_id, sinon cle
   * Kafka, sinon « _sans_node_id ») : le meme que le node_id des alertes. */
  sensor_id: string
}

/** Payload d'un capteur gridd. */
export interface SensorValue {
  node_id?: string
  type?: string
  value?: number
  unit?: string
  metadata?: {
    space?: { id?: string; label?: string }
    zone?: { id?: string; label?: string }
    building?: { id?: string; label?: string }
    storey?: { id?: string; label?: string }
  }
}

/** Entree de GET /api/topics. */
export interface TopicInfo {
  name: string
  websocket: string
}

/** Point de serie temporelle d'un capteur. */
export interface SensorPoint {
  t: number
  v: number
}

/** Etat d'un capteur : ses derniers points + le dernier message recu. */
export interface SensorSeries {
  points: SensorPoint[]
  last: SensorValue
}

export type ConnectionStatus = 'connecting' | 'live' | 'disconnected'

/** Reponse de GET /health : etat global + un booleen par consommateur Kafka. */
export interface HealthInfo {
  status: 'ok' | 'degraded'
  consumers: Record<string, boolean>
}

/** Statistiques d'une serie sur la plage affichee (une passe sur les points). */
export interface SeriesStats {
  count: number
  first: number
  firstT: number
  last: number
  lastT: number
  min: number
  minT: number
  max: number
  maxT: number
  mean: number
  delta: number
}

export type Freshness = 'fresh' | 'late' | 'stale'
export type ThemeMode = 'system' | 'light' | 'dark'
export type ViewMode = 'chart' | 'table'
/** Sens de lecture d'une hausse : neutre, ou « plus bas = mieux » (CO2, bruit). */
export type Polarity = 'neutral' | 'lower-better'

/** Ligne large du graphe/tableau : t + une colonne par node_id. */
export interface ChartRow {
  t: number
  [sensorId: string]: number
}

/** Severite d'une alerte (regles du backend, config/alerts.yaml). */
export type AlertSeverity = 'warning' | 'critical'
/** Sens de la regle : alerte au-dessus ou en dessous du seuil. */
export type AlertDirection = 'above' | 'below'
export type AlertEventKind = 'raised' | 'escalated' | 'deescalated' | 'resolved'

/** Alerte active d'un capteur (une au plus par topic et capteur). */
export interface Alert {
  /** « <topic>|<node_id> » */
  id: string
  topic: string
  node_id: string
  /** Severite, direction, seuil et hysteresis de la regle responsable. */
  severity: AlertSeverity
  direction: AlertDirection
  threshold: number
  hysteresis: number
  value: number
  /** Peut etre vide (occupation). */
  unit: string
  /** zone.label, sinon space.label, sinon vide. */
  location: string
  /** Debut de l'alerte (horodatage capteur). */
  since_ms: number
  /** Derniere mesure evaluee. */
  updated_ms: number
  /** Message du backend (journaux, autres clients de l'API). Le dashboard
   * compose le sien avec les decimales du topic : lib/alerts (alertText). */
  message: string
}

/** Changement de niveau d'une alerte. Pour « resolved », `alert` est l'etat
 * juste avant la resolution : seules `value` et `updated_ms` sont celles de
 * la mesure qui resout. Le texte de retour a la normale est compose par
 * lib/alerts (resolutionText). */
export interface AlertEvent {
  kind: AlertEventKind
  at_ms: number
  alert: Alert
}

/** Regle d'un topic : seuil franchi dans une direction, avec hysteresis. */
export interface AlertRule {
  severity: AlertSeverity
  direction: AlertDirection
  threshold: number
  hysteresis: number
}

/** Reponse de GET /api/alerts. */
export interface AlertsSnapshot {
  enabled: boolean
  /** Critical d'abord, puis since_ms croissant. */
  active: Alert[]
  /** Plus recent d'abord (200 au plus). */
  recent: AlertEvent[]
  rules: Record<string, AlertRule[]>
}

/** Message du WebSocket /ws/alerts : snapshot a la connexion, puis evenements. */
export type AlertsMessage =
  | { type: 'snapshot'; active: Alert[] }
  | { type: 'event'; event: AlertEvent }

/** Etat du flux des alertes ; « disabled » : aucune regle cote backend ;
 * « disconnected » : coupure, dernier etat connu affiche sans confirmation. */
export type AlertsStatus = 'connecting' | 'live' | 'disconnected' | 'disabled'
