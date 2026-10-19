import { useCallback, useState } from 'react'

export interface ElementSize {
  width: number
  height: number
}

const ZERO: ElementSize = { width: 0, height: 0 }

/** Boite de contenu via ResizeObserver ; ref callback a nettoyage (React 19).
 * { 0, 0 } avant montage ; le premier rappel precede la peinture (pas de saut). */
export function useElementSize<T extends Element>(): [(el: T | null) => (() => void) | undefined, ElementSize] {
  const [size, setSize] = useState<ElementSize>(ZERO)
  const ref = useCallback((el: T | null) => {
    if (!el || typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect
      if (!box) return
      // Meme taille : meme objet, aucun re-rendu
      setSize((s) => (s.width === box.width && s.height === box.height ? s : { width: box.width, height: box.height }))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, size]
}
