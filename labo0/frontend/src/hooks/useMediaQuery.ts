import { useCallback, useSyncExternalStore } from 'react'

const serverSnapshot = () => false

/** Resultat d'une media query, suivi en direct (un ecouteur par appel). */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback((onChange: () => void) => {
    const mql = window.matchMedia(query)
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [query])
  const getSnapshot = useCallback(() => window.matchMedia(query).matches, [query])
  return useSyncExternalStore(subscribe, getSnapshot, serverSnapshot)
}
