import { flushSync } from 'react-dom'

/** Applique `update` (flushSync) ; si l'element focalise a ete demonte, focus sur
 * `fallback()`, sinon <body> et Tab repartirait du lien d'evitement. Jamais
 * pendant un rendu ni dans un effet. */
export function updateKeepingFocus(update: () => void, fallback: () => HTMLElement | null): void {
  const prev = document.activeElement
  flushSync(update)
  if (prev instanceof HTMLElement && prev !== document.body && !prev.isConnected) fallback()?.focus()
}
