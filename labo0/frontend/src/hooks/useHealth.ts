import { useEffect, useState } from 'react'
import { fetchHealth } from '../api/topics'
import type { HealthInfo } from '../types'

export type HealthState = 'pending' | 'ok' | 'degraded' | 'unreachable'

/** Requete sans reponse apres ce delai (moitie de l'intervalle au plus) :
 * comptee comme un echec. Un backend fige accepte la connexion sans jamais
 * repondre, et nginx attend 60 s avant d'abandonner. */
const REQUEST_TIMEOUT_MS = 10_000

/**
 * Polling de GET /health (30 s par defaut), en pause quand l'onglet est cache.
 * La derniere reponse connue est conservee en cas d'echec ; « injoignable »
 * n'apparait qu'apres deux echecs consecutifs (erreur, ou pas de reponse dans
 * le delai). Ne bloque jamais le rendu.
 */
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
        // Annulee par le poll suivant ou le demontage : rien a compter ;
        // delai depasse : un echec comme un autre
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

    // Onglet deja cache au montage : rien ne part avant le premier retour au
    // premier plan (onVisibility fait alors poll() puis start()).
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
