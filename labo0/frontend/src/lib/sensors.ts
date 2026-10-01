/** Logique pure derivee des capteurs : noms lisibles et couleurs stables.
 * Fonctions sans React ni reseau — testables isolement. */

import type { SensorSeries } from '../types'

/**
 * Slot couleur (1-8) stable par capteur, attribue par ordre alphabetique des
 * node_id : la couleur suit le capteur, pas sa position ni le filtre actif.
 */
export function colorSlots(sensorIds: string[]): Record<string, number> {
  return Object.fromEntries(sensorIds.map((id, i) => [id, (i % 8) + 1]))
}

/**
 * Nom lisible de chaque capteur : libelle de sa zone (ou de son espace),
 * avec repli sur le node_id ; si deux capteurs partagent la meme zone, le
 * node_id est ajoute pour les distinguer.
 */
export function sensorNames(
  sensors: Record<string, SensorSeries>,
  sensorIds: string[],
): Record<string, string> {
  const names: Record<string, string> = {}
  for (const id of sensorIds) {
    const meta = sensors[id].last.metadata
    names[id] = meta?.zone?.label ?? meta?.space?.label ?? id
  }
  const counts: Record<string, number> = {}
  for (const name of Object.values(names)) counts[name] = (counts[name] ?? 0) + 1
  for (const id of sensorIds) {
    if (counts[names[id]] > 1 && names[id] !== id) names[id] = `${names[id]} (${id})`
  }
  return names
}
