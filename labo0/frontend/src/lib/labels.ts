/** Libelles lisibles des topics gridd. */

const LABELS: Record<string, string> = {
  'gridd.obs.environmental.temperature': 'Température',
  'gridd.obs.environmental.humidity': 'Humidité',
  'gridd.obs.environmental.co2': 'CO₂',
  'gridd.obs.acoustic.sound_level': 'Niveau sonore',
  'gridd.obs.occupancy.count': 'Occupation',
}

export const topicLabel = (name: string): string =>
  LABELS[name] ?? name.split('.').slice(-1)[0].replace(/_/g, ' ')
