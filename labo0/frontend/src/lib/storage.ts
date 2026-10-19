/** localStorage sans exception : si indisponible (navigation privee, politique du
 * navigateur), la lecture renvoie null et l'ecriture ne fait rien. */

export function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

/** null retire la cle. */
export function writeStored(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch {
    // stockage indisponible : le choix vaut pour la session
  }
}
