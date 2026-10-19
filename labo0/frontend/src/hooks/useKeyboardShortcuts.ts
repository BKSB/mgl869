import { useEffect, useRef } from 'react'

interface Handlers {
  /** Touches 1 a 4 : index du preset de plage. */
  onRange: (index: number) => void
  /** Touche v : graphe <-> tableau. */
  onToggleView: () => void
  /** Echap : revenir a tous les capteurs. */
  onEscape: () => void
}

/** Raccourcis globaux, ignores dans les champs de saisie et avec modificateur.
 * Un seul ecouteur ; les handlers passent par une ref. */
export function useKeyboardShortcuts(handlers: Handlers): void {
  const ref = useRef(handlers)
  useEffect(() => {
    ref.current = handlers
  })

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return
      const target = e.target
      if (target instanceof Element && target.closest('input, select, textarea, [contenteditable]')) return
      if (e.key >= '1' && e.key <= '4' && e.key.length === 1) {
        ref.current.onRange(Number(e.key) - 1)
      } else if (e.key === 'v') {
        ref.current.onToggleView()
      } else if (e.key === 'Escape') {
        ref.current.onEscape()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])
}
