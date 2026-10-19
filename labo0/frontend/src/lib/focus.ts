/** Focus clavier quand une action demonte l'element focalise. */

import { flushSync } from 'react-dom'

/**
 * Applique `update` tout de suite (flushSync), puis, si l'element qui avait
 * le focus a ete demonte (bouton qui se retire lui-meme, contenu remplace
 * par l'action), donne le focus a `fallback()` : sans cela il retomberait
 * sur <body> et le Tab suivant repartirait du lien d'evitement. A appeler
 * depuis un gestionnaire d'evenement ou un callback asynchrone, jamais
 * pendant un rendu ou dans un effet.
 */
export function updateKeepingFocus(update: () => void, fallback: () => HTMLElement | null): void {
  const prev = document.activeElement
  flushSync(update)
  if (prev instanceof HTMLElement && prev !== document.body && !prev.isConnected) fallback()?.focus()
}
