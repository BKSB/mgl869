/** Logique pure des alertes (sans React ni reseau) : tri, application d'un
 * evenement, severite dominante et libelles. */

import type { Alert, AlertEvent, AlertEventKind, AlertSeverity } from '../types'
import { fmtValue } from './format'
import { topicLabel } from './labels'
import { getTopicMeta } from './metrics'

export const SEVERITY_RANK: Record<AlertSeverity, number> = { warning: 1, critical: 2 }

/** Libelle visible de la severite (panneau). */
export const SEVERITY_LABEL: Record<AlertSeverity, string> = {
  warning: 'Avertissement',
  critical: 'Critique',
}

/** Texte lu par les lecteurs d'ecran a cote de l'icone de severite. */
export const SEVERITY_SR: Record<AlertSeverity, string> = {
  warning: 'Avertissement',
  critical: 'Alerte critique',
}

/** Libelle d'un evenement (section « Récemment »). */
export function eventLabel(kind: AlertEventKind, severity: AlertSeverity): string {
  switch (kind) {
    case 'raised': return severity === 'critical' ? 'Déclenchée (critique)' : 'Déclenchée (avertissement)'
    case 'escalated': return 'Passée en critique'
    case 'deescalated': return 'Revenue en avertissement'
    case 'resolved': return 'Résolue'
  }
}

/** Seuil d'une regle : entier sans decimale (« 1 000 ppm », « 18 °C »),
 * sinon avec les decimales du topic (« 17,5 °C »). */
export function fmtThreshold(threshold: number, decimals: number, unit: string): string {
  return fmtValue(threshold, Number.isInteger(threshold) ? 0 : decimals, unit)
}

/** Decimales ajoutees au plus pour distinguer une valeur d'une limite. */
const EXTRA_DECIMALS = 3

/** Valeur mesuree aux decimales du topic, avec jusqu'a 3 decimales de plus
 * quand l'arrondi la confondrait avec une limite (seuil, fin de bande)
 * qu'elle ne vaut pas : 26,04 au-dessus de 26 s'ecrit « 26,04 °C », pas
 * « 26,0 °C ». */
function fmtMeasured(value: number, decimals: number, unit: string, ...limits: number[]): string {
  let d = decimals
  while (d < decimals + EXTRA_DECIMALS && limits.some((l) => l !== value && fmtValue(l, d) === fmtValue(value, d))) d += 1
  return fmtValue(value, d, unit)
}

/**
 * Texte d'une alerte active, compose a partir des champs structures avec les
 * libelles et les decimales du dashboard, comme les tiles (le `message` du
 * backend sert aux journaux et aux autres clients de l'API). Au-dela du
 * seuil : « CO₂ au-dessus de 1 000 ppm (1 120 ppm) ». Maintenue par
 * l'hysteresis : « CO₂ à 960 ppm (seuil 1 000 ppm), alerte maintenue
 * jusqu’à 950 ppm » (« niveau critique maintenu » pour une alerte critique,
 * qui redescend en avertissement en sortant de sa bande).
 */
export function alertText(a: Alert): string {
  const { decimals } = getTopicMeta(a.topic)
  const label = topicLabel(a.topic)
  const threshold = fmtThreshold(a.threshold, decimals, a.unit)
  const above = a.direction === 'above'
  if (above ? a.value > a.threshold : a.value < a.threshold) {
    const value = fmtMeasured(a.value, decimals, a.unit, a.threshold)
    return `${label} ${above ? 'au-dessus de' : 'en dessous de'} ${threshold} (${value})`
  }
  const release = above ? a.threshold - a.hysteresis : a.threshold + a.hysteresis
  const held = a.severity === 'critical' ? 'niveau critique maintenu' : 'alerte maintenue'
  const value = fmtMeasured(a.value, decimals, a.unit, a.threshold, release)
  return `${label} à ${value} (seuil ${threshold}), ${held} jusqu’à ${fmtThreshold(release, decimals, a.unit)}`
}

/** Texte d'un evenement « resolved ». Le contrat garde dans `alert` l'etat
 * juste avant la resolution : seules la valeur et l'heure sont celles de la
 * mesure qui resout. Le retour a la normale est donc compose ici, ex.
 * « CO₂ de nouveau sous 1 000 ppm (940 ppm) ». */
export function resolutionText(a: Alert): string {
  const { decimals } = getTopicMeta(a.topic)
  const where = a.direction === 'above' ? 'sous' : 'au-dessus de'
  const value = fmtMeasured(a.value, decimals, a.unit, a.threshold)
  return `${topicLabel(a.topic)} de nouveau ${where} ${fmtThreshold(a.threshold, decimals, a.unit)} (${value})`
}

/** Texte d'un evenement (« Récemment », annonces) : texte de l'alerte, ou
 * retour a la normale pour « resolved ». */
export const eventText = (e: AlertEvent): string =>
  e.kind === 'resolved' ? resolutionText(e.alert) : alertText(e.alert)

/** Ordre du contrat : critical d'abord, puis la plus ancienne, puis l'id. */
export function compareAlerts(a: Alert, b: Alert): number {
  return SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity]
    || a.since_ms - b.since_ms
    || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)
}

export function sortAlerts(alerts: Alert[]): Alert[] {
  return [...alerts].sort(compareAlerts)
}

/** Alertes actives apres un evenement : « resolved » retire l'alerte, les
 * autres la remplacent (ou l'ajoutent). Tableau neuf, toujours trie. */
export function applyEvent(active: Alert[], event: AlertEvent): Alert[] {
  const rest = active.filter((a) => a.id !== event.alert.id)
  if (event.kind === 'resolved') return rest
  return sortAlerts([...rest, event.alert])
}

/** Cle d'identite d'un evenement : un evenement deja connu (GET puis flux)
 * n'est pas ajoute deux fois aux recents. */
export const eventKey = (e: AlertEvent): string => `${e.kind}|${e.at_ms}|${e.alert.id}`

/** Severite la plus haute d'une liste, ou null si elle est vide. */
export function highestSeverity(alerts: readonly Alert[]): AlertSeverity | null {
  let best: AlertSeverity | null = null
  for (const a of alerts) {
    if (a.severity === 'critical') return 'critical'
    best = 'warning'
  }
  return best
}

/** « 1 alerte », « 3 alertes ». */
export const alertCount = (n: number): string => `${n} alerte${n > 1 ? 's' : ''}`

/** Lieu lisible d'une alerte : emplacement, sinon identifiant du capteur. */
export const alertPlace = (a: Alert): string => a.location || a.node_id

/** Phrase annoncee aux lecteurs d'ecran a l'arrivee d'un evenement. */
export function announcement(e: AlertEvent): string {
  const where = alertPlace(e.alert)
  switch (e.kind) {
    case 'raised':
      return `${e.alert.severity === 'critical' ? 'Nouvelle alerte critique' : 'Nouvel avertissement'} : ${alertText(e.alert)}, ${where}`
    case 'escalated': return `Alerte passée en critique : ${alertText(e.alert)}, ${where}`
    case 'deescalated': return `Alerte revenue en avertissement : ${alertText(e.alert)}, ${where}`
    case 'resolved': return `Alerte résolue : ${resolutionText(e.alert)}, ${where}`
  }
}
