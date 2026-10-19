/** Focus itinerant (roving tabindex) des groupes radio et des onglets. */

/** Index cible (fleches en boucle, Home, End), sinon null. `vertical: false`
 * ignore haut / bas (onglets horizontaux). */
export function rovingIndex(key: string, i: number, n: number, { vertical = true } = {}): number | null {
  switch (key) {
    case 'ArrowLeft': return (i - 1 + n) % n
    case 'ArrowRight': return (i + 1) % n
    case 'ArrowUp': return vertical ? (i - 1 + n) % n : null
    case 'ArrowDown': return vertical ? (i + 1) % n : null
    case 'Home': return 0
    case 'End': return n - 1
    default: return null
  }
}
