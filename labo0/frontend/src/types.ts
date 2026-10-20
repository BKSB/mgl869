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
  value: number
  /** Avec unite (« W > 26 °C ») */
  text: string
  /** Sans unite (« W > 26 »), pour les pieds de tuile */
  short: string
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

interface ViewBase {
  type: 'view'
  site: string
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

export type View = RoomsData | MetricData | AlertsData

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

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected'
