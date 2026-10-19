import { useCallback, useEffect, useId, useRef, useState } from 'react'
import type { FocusEvent } from 'react'
import { AlertsPanel } from './AlertsPanel'
import { Icon } from './Icon'
import type { IconName } from './Icon'
import { announcement, highestSeverity } from '../lib/alerts'
import { RECONNECT_TEXT } from '../lib/stream'
import type { Alert, AlertEvent, AlertsStatus } from '../types'

interface Props {
  loaded: boolean
  status: AlertsStatus
  active: Alert[]
  recent: AlertEvent[]
  latest: AlertEvent | null
  /** « Voir » : selectionne le topic de l'alerte et isole son capteur. */
  onShow: (alert: Alert) => void
}

/** Detail lu apres le libelle : « 1 critique, 2 avertissements ». */
function breakdown(active: Alert[]): string {
  const critical = active.filter((a) => a.severity === 'critical').length
  const warning = active.length - critical
  const parts: string[] = []
  if (critical) parts.push(`${critical} critique${critical > 1 ? 's' : ''}`)
  if (warning) parts.push(`${warning} avertissement${warning > 1 ? 's' : ''}`)
  return parts.join(', ')
}

/**
 * Puce des alertes dans l'app bar (meme anatomie que HealthChip : icone de
 * statut + libelle, libelle sr-only sous 720 px). C'est un bouton qui ouvre
 * un panneau non modal ancre sous la puce : fermeture par Echap, clic
 * exterieur, bouton Fermer ou focus parti ailleurs ; le focus entre dans le
 * panneau a l'ouverture et revient a la puce a la fermeture au clavier.
 */
export function AlertsChip({ loaded, status, active, recent, latest, onShow }: Props) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const panelId = useId()
  const titleId = useId()

  const close = useCallback((refocus: boolean) => {
    setOpen(false)
    if (refocus) buttonRef.current?.focus()
  }, [])

  // Panneau ouvert : focus sur le panneau (nom annonce), Echap et clic
  // exterieur. Echap est intercepte en capture : le raccourci global Echap
  // (revenir a tous les capteurs) ne s'applique pas tant que le panneau est
  // ouvert.
  useEffect(() => {
    if (!open) return
    panelRef.current?.focus()
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.stopPropagation()
      e.preventDefault()
      const active = document.activeElement
      const inside = active === document.body || (active !== null && !!wrapRef.current?.contains(active))
      close(inside)
    }
    const onPointerDown = (e: PointerEvent) => {
      if (e.target instanceof Node && !wrapRef.current?.contains(e.target)) close(false)
    }
    document.addEventListener('keydown', onKeyDown, true)
    document.addEventListener('pointerdown', onPointerDown, true)
    return () => {
      document.removeEventListener('keydown', onKeyDown, true)
      document.removeEventListener('pointerdown', onPointerDown, true)
    }
  }, [open, close])

  // Focus parti hors de la puce et du panneau (Tab apres le dernier bouton) :
  // le panneau se ferme pour ne pas masquer l'element focalise. Un focus
  // perdu sans destination (clic sur du texte du panneau) ne ferme rien.
  const onBlur = (e: FocusEvent<HTMLDivElement>) => {
    const next = e.relatedTarget
    if (open && next instanceof Node && !e.currentTarget.contains(next)) setOpen(false)
  }

  const show = (alert: Alert) => {
    onShow(alert)
    close(true)
  }

  const n = active.length
  const top = highestSeverity(active)
  let icon: IconName
  let tone: string
  let label: string
  if (status === 'disabled') {
    icon = 'bell-off'; tone = 'muted'; label = 'Alertes désactivées'
  } else if (!loaded) {
    icon = 'clock'; tone = 'muted'; label = 'Alertes : …'
  } else if (top === null) {
    // Flux coupe : « aucune alerte » n'est plus confirme, la coche passe en
    // neutre (une alerte connue garde au contraire son icone de severite).
    // L'etat reste « disconnected » pendant les tentatives, jusqu'a une
    // reponse fraiche du backend : la coche ne repasse pas au vert avant.
    icon = 'check-circle'; tone = status === 'disconnected' ? 'muted' : 'good'; label = 'Aucune alerte'
  } else {
    icon = top === 'critical' ? 'alert-octagon' : 'alert-triangle'
    tone = top
    label = `Alertes : ${n}`
  }
  const detail = n > 0 ? ` (${breakdown(active)})` : ''
  const stale = status === 'disconnected' && loaded ? ` · flux interrompu, ${RECONNECT_TEXT}` : ''
  const live = latest ? announcement(latest) : ''

  return (
    <div className="alerts" ref={wrapRef} onBlur={onBlur}>
      <button
        ref={buttonRef}
        type="button"
        className={`badge badge--${tone} badge--button`}
        aria-label={`${label}${detail}`}
        aria-expanded={open}
        aria-controls={panelId}
        aria-haspopup="dialog"
        title={`${label}${detail}${stale}`}
        onClick={() => setOpen((o) => !o)}
      >
        <Icon name={icon} size={14} className="badge__icon" />
        <span className="badge__label">{label}</span>
      </button>
      <div
        ref={panelRef}
        id={panelId}
        className="alerts-panel"
        role="dialog"
        aria-modal="false"
        aria-labelledby={titleId}
        tabIndex={-1}
        hidden={!open}
      >
        {open && (
          <AlertsPanel
            titleId={titleId} loaded={loaded} status={status} active={active} recent={recent}
            onShow={show} onClose={() => close(true)}
          />
        )}
      </div>
      {/* Annonce polie de chaque evenement recu en direct (pas du GET initial) */}
      <span className="sr-only" role="status" aria-live="polite">{live}</span>
    </div>
  )
}
