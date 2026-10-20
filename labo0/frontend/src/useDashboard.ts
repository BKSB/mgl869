import { useCallback, useEffect, useRef, useState } from 'react'
import { wsUrl } from './api'
import type { ConnectionStatus, DashboardMessage, Toast, View, ViewParams } from './types'

const RECONNECT_DELAY_MS = 3000
const TOAST_TTL_MS = 15_000
const TOAST_MAX = 4
/** Un zoom qui glisse change les parametres plusieurs fois par seconde */
const SEND_DEBOUNCE_MS = 60

export interface Dashboard {
  status: ConnectionStatus
  /** Derniere vue recue, quelle que soit la route demandee. */
  view: View | null
  toasts: Toast[]
  dismiss: (id: string) => void
}

/** Un seul WebSocket : les parametres partent a chaque changement et a chaque
 * reconnexion ; le backend repond par la vue complete, puis la repousse a
 * chaque changement de donnees. Coupure : derniere vue conservee, etat
 * « déconnecté », nouvel essai toutes les 3 s. */
export function useDashboard(params: ViewParams): Dashboard {
  const [status, setStatus] = useState<ConnectionStatus>('connecting')
  const [view, setView] = useState<View | null>(null)
  const [toasts, setToasts] = useState<Toast[]>([])
  const socket = useRef<WebSocket | null>(null)
  const paramsJson = JSON.stringify(params)
  const latest = useRef(paramsJson)

  const dismiss = useCallback((id: string) => {
    setToasts((current) => current.filter((t) => t.id !== id))
  }, [])

  useEffect(() => {
    let closed = false
    let timer: number | undefined

    const connect = () => {
      const ws = new WebSocket(wsUrl('/ws/dashboard'))
      socket.current = ws
      ws.onopen = () => {
        setStatus('connected')
        ws.send(latest.current)
      }
      ws.onmessage = (e: MessageEvent<string>) => {
        let message: DashboardMessage
        try {
          message = JSON.parse(e.data) as DashboardMessage
        } catch {
          return
        }
        if (message.type === 'view') {
          setView(message)
        } else if (message.type === 'toast') {
          setToasts((current) => [message, ...current.filter((t) => t.id !== message.id)].slice(0, TOAST_MAX))
          window.setTimeout(() => dismiss(message.id), TOAST_TTL_MS)
        }
      }
      ws.onclose = () => {
        if (closed) return
        socket.current = null
        setStatus('disconnected')
        timer = window.setTimeout(connect, RECONNECT_DELAY_MS)
      }
    }

    connect()
    return () => {
      closed = true
      window.clearTimeout(timer)
      socket.current?.close()
      socket.current = null
    }
  }, [dismiss])

  useEffect(() => {
    latest.current = paramsJson
    const timer = window.setTimeout(() => {
      if (socket.current?.readyState === WebSocket.OPEN) socket.current.send(paramsJson)
    }, SEND_DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [paramsJson])

  return { status, view, toasts, dismiss }
}
