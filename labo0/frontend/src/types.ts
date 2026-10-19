/** Message Kafka diffuse par le backend sur /ws/<topic>. */
export interface TopicRecord {
  topic: string
  partition: number
  offset: number
  timestamp_ms: number
  key: string | null
  value: SensorValue | string | null
  /** Calcule par le backend : node_id, sinon cle Kafka, sinon « _sans_node_id ».
   * Meme valeur que Alert.node_id. */
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

export interface SensorPoint {
  t: number
  v: number
}

/** last : dernier payload recu (unite, metadonnees). */
export interface SensorSeries {
  points: SensorPoint[]
  last: SensorValue
}

export type ConnectionStatus = 'connecting' | 'live' | 'disconnected'

/** Classe badge--<tone> : couleur de l'icone d'un badge d'etat. */
export type Tone = 'good' | 'warning' | 'critical' | 'muted'

/** Reponse de GET /health : un booleen par consommateur Kafka. */
export interface HealthInfo {
  status: 'ok' | 'degraded'
  consumers: Record<string, boolean>
}

/** Statistiques d'une serie sur la plage affichee. */
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
/** Sens d'une hausse : neutre, ou « plus bas = mieux » (CO2, bruit). */
export type Polarity = 'neutral' | 'lower-better'

/** Ligne large du graphe/tableau : t + une colonne par node_id. */
export interface ChartRow {
  t: number
  [sensorId: string]: number
}

/** Cf. regles du backend (config/alerts.yaml). */
export type AlertSeverity = 'warning' | 'critical'
export type AlertDirection = 'above' | 'below'
export type AlertEventKind = 'raised' | 'escalated' | 'deescalated' | 'resolved'

/** Alerte active : une au plus par topic et capteur. */
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
  /** Pour les journaux et autres clients : le dashboard compose le sien (alertText). */
  message: string
}

/** Pour « resolved », `alert` est l'etat juste avant la resolution, sauf
 * `value` et `updated_ms` : ceux de la mesure qui resout. */
export interface AlertEvent {
  kind: AlertEventKind
  at_ms: number
  alert: Alert
}

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

/** /ws/alerts : snapshot a la connexion, puis evenements. */
export type AlertsMessage =
  | { type: 'snapshot'; active: Alert[] }
  | { type: 'event'; event: AlertEvent }

/** « disabled » : aucune regle cote backend ; « disconnected » : dernier etat connu, non confirme. */
export type AlertsStatus = 'connecting' | 'live' | 'disconnected' | 'disabled'
