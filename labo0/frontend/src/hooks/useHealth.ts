import { useEffect, useState } from 'react'
import { fetchHealth } from '../api/topics'
import type { HealthInfo } from '../types'

export type HealthState = 'pending' | 'ok' | 'degraded' | 'unreachable'

/** Sans reponse dans ce delai (borne a intervalle / 2) : echec. Un backend fige
 * accepte la connexion sans repondre, et nginx attend 60 s avant d'abandonner. */
const REQUEST_TIMEOUT_MS = 10_000

/** Polling de GET /health, en pause onglet cache. Derniere reponse gardee en cas
 * d'echec ; « unreachable » seulement apres deux echecs consecutifs. */
export function useHealth(intervalMs = 30_000): {
  health: HealthInfo | null
  state: HealthState
} {
  const [health, setHealth] = useState<HealthInfo | null>(null)
  const [state, setState] = useState<HealthState>('pending')

  useEffect(() => {
    let failures = 0
    let disposed = false
    let controller: AbortController | null = null
    let timer: number | undefined
    const timeoutMs = Math.min(REQUEST_TIMEOUT_MS, intervalMs / 2)

    const poll = async () => {
      controller?.abort()
      const current = new AbortController()
      controller = current
      let timedOut = false
      const timeout = window.setTimeout(() => {
        timedOut = true
        current.abort()
      }, timeoutMs)
      try {
        const body = await fetchHealth(current.signal)
        if (disposed || current.signal.aborted) return
        failures = 0
        setHealth(body)
        setState(body.status === 'ok' ? 'ok' : 'degraded')
      } catch {
        // Annulee (poll suivant, demontage) : rien a compter ; delai depasse : echec
        if (disposed || (current.signal.aborted && !timedOut)) return
        failures += 1
        if (failures >= 2) setState('unreachable')
      } finally {
        window.clearTimeout(timeout)
      }
    }
    const start = () => {
      if (timer === undefined) timer = window.setInterval(() => void poll(), intervalMs)
    }
    const stop = () => {
      window.clearInterval(timer)
      timer = undefined
    }
    const onVisibility = () => {
      if (document.hidden) stop()
      else { void poll(); start() }
    }

    // Onglet cache au montage : premier poll au retour au premier plan (onVisibility)
    if (!document.hidden) {
      void poll()
      start()
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      disposed = true
      controller?.abort()
      stop()
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [intervalMs])

  return { health, state }
}
