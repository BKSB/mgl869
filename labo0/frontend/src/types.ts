/** Message Kafka tel que diffuse par le backend sur /ws/<topic>. */
export interface TopicRecord {
  topic: string
  partition: number
  offset: number
  timestamp_ms: number
  key: string | null
  value: SensorValue | string | null
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
