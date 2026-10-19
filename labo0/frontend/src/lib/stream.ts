/** Flux WebSocket (topics et alertes) : delai de reconnexion et etats
 * d'attente, une seule source pour les hooks et les textes de l'interface. */

import { fmtDuration } from './format'
import type { ConnectionStatus } from '../types'

/** Delai entre deux tentatives de reconnexion d'un WebSocket coupe. */
export const RECONNECT_DELAY_MS = 3000

/** « reconnexion toutes les 3 s » : reste vrai pendant toute la coupure. */
export const RECONNECT_TEXT = `reconnexion toutes les ${fmtDuration(RECONNECT_DELAY_MS)}`

/** Raison pour laquelle le topic affiche n'a encore aucun capteur. */
export type EmptyKind = 'connecting' | 'replaying' | 'waiting' | 'disconnected'

/** Libelle court de chaque raison : sous-titre de la carte et tiles. */
export const EMPTY_LABEL: Record<EmptyKind, string> = {
  connecting: 'Connexion au flux…',
  replaying: 'Rejeu de l’historique…',
  waiting: 'En attente de données…',
  disconnected: 'Flux interrompu',
}

/** Coupure du flux d'un topic, detaillee : bandeau et corps de la carte. */
export const DISCONNECTED_TEXT = `${EMPTY_LABEL.disconnected} — ${RECONNECT_TEXT}`

/** Raison de l'etat vide, ou null si des capteurs sont connus. `waiting` :
 * flux ouvert sans aucun message depuis plusieurs secondes (topic muet). */
export function emptyKind(empty: boolean, status: ConnectionStatus, waiting: boolean): EmptyKind | null {
  if (!empty) return null
  if (waiting) return 'waiting'
  return status === 'live' ? 'replaying' : status
}
