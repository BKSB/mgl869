import { useSyncExternalStore } from 'react'

/** Ticker partage (module) : un seul setInterval pour tous les abonnes,
 * 5 s de resolution, en pause quand l'onglet est cache. */

const TICK_MS = 5000

let now = Date.now()
let timer: number | undefined
const listeners = new Set<() => void>()

function tick() {
  now = Date.now()
  for (const l of listeners) l()
}
function start() {
  if (timer === undefined) timer = window.setInterval(tick, TICK_MS)
}
function stop() {
  window.clearInterval(timer)
  timer = undefined
}
function onVisibility() {
  if (document.hidden) stop()
  else { tick(); start() }
}
function subscribe(listener: () => void): () => void {
  if (listeners.size === 0) {
    now = Date.now()
    document.addEventListener('visibilitychange', onVisibility)
    if (!document.hidden) start()
  }
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
    if (listeners.size === 0) {
      stop()
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }
}
const getNow = () => now

/** Horloge courante (ms), rafraichie toutes les 5 s. */
export function useNow(): number {
  return useSyncExternalStore(subscribe, getNow, getNow)
}
