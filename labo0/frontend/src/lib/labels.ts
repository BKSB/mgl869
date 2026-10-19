/** Libelles lisibles des topics gridd. */

const LABELS: Record<string, string> = {
  'gridd.obs.environmental.temperature': 'Température',
  'gridd.obs.environmental.humidity': 'Humidité',
  'gridd.obs.environmental.co2': 'CO₂',
  'gridd.obs.acoustic.sound_level': 'Niveau sonore',
  'gridd.obs.occupancy.count': 'Occupation',
}

/** Libelle d'un topic ; repli sur le dernier segment du nom, avec une
 * majuscule, comme les messages du backend (« Wind speed »). */
export function topicLabel(name: string): string {
  const label = LABELS[name]
  if (label) return label
  const last = name.split('.').slice(-1)[0].replace(/_/g, ' ')
  return last.charAt(0).toUpperCase() + last.slice(1)
}
