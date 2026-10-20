/** Messages de /ws/dashboard (et reponse de GET /api/dashboard) : libelles,
 * nombres, etats et tris sont deja decides par le backend. */

export type Status = 'normal' | 'warning' | 'critical'
export type AlertState = 'active' | 'acknowledged' | 'resolved'

export interface Option {
  id: string
  label: string
}

export interface RoomRef {
  id: string
  name: string
  floor: string
}

export interface Threshold {
  severity: Status
  direction: 'above' | 'below'
  value: number
  /** Avec unite (« W > 26 °C ») */
  text: string
  /** Sans unite (« W > 26 »), pour les pieds de tuile */
  short: string
  /** Ligne du graphe (« Seuil erreur 1 500 ») */
  label: string
}

export interface SensorTile {
  id: string
  metric: string
  label: string
  unit: string
  room: RoomRef
  value_text: string
  status: Status
  status_label: string
  updated_ms: number
  thresholds: Threshold[]
  /** [horodatage ms, valeur], tries, 120 au plus */
  points: [number, number][]
  stats_text: string
}

export interface RoomSummary extends RoomRef {
  status: Status
}

export interface RoomDetail extends RoomRef {
  building: string
  status: Status
  status_label: string
  summary: string
  last_ms: number
  range: string
  sensors: SensorTile[]
}

export interface MetricDetail {
  id: string
  label: string
  unit: string
  thresholds: Threshold[]
  summary: string
  counts: { status: Status; text: string }[]
  range: string
  sort: string
  sorts: Option[]
  sensors: SensorTile[]
}

export interface AlertRow {
  id: string
  key: string
  severity: Status
  severity_label: string
  room: RoomRef
  metric_label: string
  sensor_id: string
  value_text: string
  threshold_text: string
  since_ms: number
  state: AlertState
  state_label: string
  state_ms: number | null
  can_ack: boolean
}

export interface Filter extends Option {
  count: number | null
}

/** Somme des capteurs d'occupation ; null sans capteur d'occupation. */
export interface People {
  count_text: string
  label: string
  updated_ms: number
}

interface ViewBase {
  type: 'view'
  /** « Local A-1540 » */
  site: string
  people: People | null
  alerts_enabled: boolean
  alerts_active: number
  ranges: Option[]
}

export interface RoomsData extends ViewBase {
  view: 'rooms'
  rooms: RoomSummary[]
  room: RoomDetail | null
}

export interface MetricData extends ViewBase {
  view: 'metric'
  metrics: Option[]
  metric: MetricDetail | null
}

export interface AlertsData extends ViewBase {
  view: 'alerts'
  filter: string
  filters: Filter[]
  summary: string
  alerts: AlertRow[]
}

/** [debut de case ms, moyenne, etat, moyenne formatee] */
export type ChartPoint = [number, number, Status, string]

export interface ChartStats {
  /** « zoom » ou le libelle de la plage */
  scope: string
  min: { text: string; status: Status }
  max: { text: string; status: Status }
  mean: { text: string }
  alerts: { status: Status; text: string }[]
}

export interface ChartDetail {
  metric: string
  label: string
  unit: string
  sensor_id: string
  room: RoomRef
  value_text: string
  status: Status
  updated_ms: number
  range: string
  range_label: string
  ranges: Option[]
  overview_label: string
  /** Bornes de la plage, [debut, fin] */
  span: [number, number]
  /** Fenetre de zoom appliquee par le backend (bornee), null sans zoom */
  zoom: [number, number] | null
  thresholds: Threshold[]
  /** Toute la plage ; le zoom ne fait que filtrer l'affichage */
  series: ChartPoint[]
  /** Sur la fenetre de zoom ; null sans donnee */
  stats: ChartStats | null
  csv_url: string
}

export interface ChartData extends ViewBase {
  view: 'chart'
  chart: ChartDetail | null
}

export type View = RoomsData | MetricData | AlertsData | ChartData

export interface Toast {
  type: 'toast'
  id: string
  severity: Status
  severity_label: string
  at_ms: number
  title: string
  value_text: string
  text: string
  alert_id: string
  room_id: string
}

export type DashboardMessage = View | Toast

/** Parametres de la vue, envoyes tels quels au backend (dashboard_views.py). */
export type ViewParams =
  | { view: 'rooms'; room?: string; range: string }
  | { view: 'metric'; metric?: string; range: string; sort: string }
  | { view: 'alerts'; filter: string }
  | { view: 'chart'; metric: string; sensor: string; range: string; from?: number; to?: number }

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected'
