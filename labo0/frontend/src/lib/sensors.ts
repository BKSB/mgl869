/** Noms lisibles et couleurs stables des capteurs (logique pure). */

import type { SensorSeries } from '../types'

/** Slot 1-8 dans l'ordre de `sensorIds` (tri naturel fait par App) : la couleur
 * suit le capteur, pas le filtre actif. */
export function colorSlots(sensorIds: string[]): Record<string, number> {
  return Object.fromEntries(sensorIds.map((id, i) => [id, (i % 8) + 1]))
}

/** Zone, sinon espace, sinon node_id (libelle vide ignore, comme le backend) ;
 * node_id ajoute quand deux capteurs partagent un nom. */
export function sensorNames(
  sensors: Record<string, SensorSeries>,
  sensorIds: string[],
): Record<string, string> {
  const names: Record<string, string> = {}
  for (const id of sensorIds) {
    const meta = sensors[id].last.metadata
    names[id] = meta?.zone?.label || meta?.space?.label || id
  }
  const counts: Record<string, number> = {}
  for (const name of Object.values(names)) counts[name] = (counts[name] ?? 0) + 1
  for (const id of sensorIds) {
    if (counts[names[id]] > 1 && names[id] !== id) names[id] = `${names[id]} (${id})`
  }
  return names
}
