import { useCallback, useState } from 'react'

export interface ElementSize {
  width: number
  height: number
}

const ZERO: ElementSize = { width: 0, height: 0 }

/** Taille de la boite de contenu d'un element, suivie par ResizeObserver.
 * Renvoie un ref callback (nettoyage React 19) et la derniere taille mesuree ;
 * { 0, 0 } tant que l'element n'est pas monte. Le premier rappel de
 * l'observateur arrive avant la premiere peinture : aucun saut visible. */
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
