import { useCallback, useEffect, useMemo, useReducer } from 'react'
import { fetchAlerts, wsUrl } from '../api/topics'
import { applyEvent, eventKey, sortAlerts } from '../lib/alerts'
import { RECONNECT_DELAY_MS } from '../lib/stream'
import type { Alert, AlertEvent, AlertRule, AlertsMessage, AlertsSnapshot, AlertsStatus } from '../types'

const RECENT_MAX = 50
/** Alertes desactivees : GET refait a ce rythme (le backend peut redemarrer avec des regles). */
const DISABLED_RECHECK_MS = 30_000

interface State {
  loaded: boolean
  status: AlertsStatus
  active: Alert[]
  recent: AlertEvent[]
  rules: Record<string, AlertRule[]>
  latest: AlertEvent | null
}

type Action =
  | { type: 'loaded'; snapshot: AlertsSnapshot }
  | { type: 'snapshot'; active: Alert[] }
  | { type: 'event'; event: AlertEvent }
  | { type: 'disconnected' }

const INITIAL: State = { loaded: false, status: 'connecting', active: [], recent: [], rules: {}, latest: null }

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'loaded': {
      const { enabled, active, recent, rules } = action.snapshot
      return {
        ...state,
        loaded: true,
        status: enabled ? 'connecting' : 'disabled',
        active: enabled ? sortAlerts(active) : [],
        recent: enabled ? recent.slice(0, RECENT_MAX) : [],
        rules: enabled ? rules : {},
      }
    }
    case 'snapshot':
      // Le snapshot fait foi : re-synchro apres reconnexion, evenements manques compris
      return { ...state, status: 'live', active: sortAlerts(action.active) }
    case 'event': {
      const key = eventKey(action.event)
      const known = state.recent.some((e) => eventKey(e) === key)
      return {
        ...state,
        active: applyEvent(state.active, action.event),
        recent: known ? state.recent : [action.event, ...state.recent].slice(0, RECENT_MAX),
        latest: action.event,
      }
    }
    case 'disconnected':
      // Desactivees : un GET de reverification en echec n'est pas une coupure du flux
      return state.status === 'disabled' ? state : { ...state, status: 'disconnected' }
  }
}

const NO_ALERTS: Alert[] = []
const NO_SENSORS: Record<string, Alert> = {}

export interface AlertsApi {
  /** Au moins une reponse de GET /api/alerts (sinon l'etat est inconnu). */
  loaded: boolean
  status: AlertsStatus
  /** Critical d'abord, puis la plus ancienne. */
  active: Alert[]
  /** Plus recent d'abord, 50 au plus. */
  recent: AlertEvent[]
  rules: Record<string, AlertRule[]>
  /** Dernier evenement recu en direct, jamais du GET initial (annonces). */
  latest: AlertEvent | null
  /** Reference stable tant que les alertes actives ne changent pas. */
  byTopic: (topic: string | null) => Alert[]
  /** Par node_id ; reference stable aussi. */
  bySensor: (topic: string | null) => Record<string, Alert>
}

/** GET /api/alerts puis WebSocket /ws/alerts. Coupure : « disconnected » jusqu'a une
 * reponse fraiche du GET (tentatives toutes les 3 s), puis le snapshot re-synchronise.
 * Sans regles : « disabled », sans WebSocket. Dispatch uniquement depuis des
 * callbacks asynchrones, jamais dans le corps de l'effet. */
export function useAlerts(): AlertsApi {
  const [state, dispatch] = useReducer(reducer, INITIAL)

  useEffect(() => {
    let disposed = false
    let ws: WebSocket | null = null
    let controller: AbortController | null = null
    let timer: number | undefined

    const connectLater = (delay: number) => {
      timer = window.setTimeout(() => void connect(), delay)
    }

    const retryLater = () => {
      if (disposed) return
      dispatch({ type: 'disconnected' })
      connectLater(RECONNECT_DELAY_MS)
    }

    const openSocket = () => {
      const socket = new WebSocket(wsUrl('alerts'))
      ws = socket
      socket.onmessage = (e: MessageEvent<string>) => {
        let msg: AlertsMessage
        try {
          msg = JSON.parse(e.data) as AlertsMessage
        } catch {
          return
        }
        if (msg.type === 'snapshot') dispatch({ type: 'snapshot', active: msg.active })
        else if (msg.type === 'event') dispatch({ type: 'event', event: msg.event })
      }
      socket.onclose = () => {
        if (ws !== socket) return
        ws = null
        retryLater()
      }
    }

    const connect = async () => {
      const current = new AbortController()
      controller = current
      try {
        const snapshot = await fetchAlerts(current.signal)
        if (disposed || current.signal.aborted) return
        dispatch({ type: 'loaded', snapshot })
        if (snapshot.enabled) openSocket()
        else connectLater(DISABLED_RECHECK_MS)
      } catch {
        if (disposed || current.signal.aborted) return
        retryLater()
      }
    }

    void connect()
    return () => {
      disposed = true
      controller?.abort()
      window.clearTimeout(timer)
      const socket = ws
      ws = null
      if (socket) {
        socket.onclose = null
        socket.close()
      }
    }
  }, [])

  // References stables pour les composants memo en aval
  const index = useMemo(() => {
    const topics: Record<string, Alert[]> = {}
    const sensors: Record<string, Record<string, Alert>> = {}
    for (const a of state.active) {
      topics[a.topic] ??= []
      topics[a.topic].push(a)
      sensors[a.topic] ??= {}
      sensors[a.topic][a.node_id] = a
    }
    return { topics, sensors }
  }, [state.active])
  const byTopic = useCallback((topic: string | null) => (topic && index.topics[topic]) || NO_ALERTS, [index])
  const bySensor = useCallback((topic: string | null) => (topic && index.sensors[topic]) || NO_SENSORS, [index])

  return {
    loaded: state.loaded,
    status: state.status,
    active: state.active,
    recent: state.recent,
    rules: state.rules,
    latest: state.latest,
    byTopic,
    bySensor,
  }
}
