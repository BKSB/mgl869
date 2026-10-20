import { useEffect, useState } from 'react'
import type { RefObject } from 'react'

/** Largeur rendue d'un element (graphes SVG en pixels, texte net). */
export function useWidth(ref: RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const element = ref.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(element)
    setWidth(element.clientWidth)
    return () => observer.disconnect()
  }, [ref])
  return width
}
