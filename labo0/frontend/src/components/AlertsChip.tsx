import { useCallback, useEffect, useId, useRef, useState } from 'react'
import type { FocusEvent } from 'react'
import { AlertsPanel } from './AlertsPanel'
import { Icon } from './Icon'
import type { IconName } from './Icon'
import { announcement, highestSeverity } from '../lib/alerts'
import { plural } from '../lib/format'
import { RECONNECT_TEXT } from '../lib/stream'
import type { Alert, AlertEvent, AlertSeverity, AlertsStatus, Tone } from '../types'

interface Props {
  loaded: boolean
  status: AlertsStatus
  active: Alert[]
  recent: AlertEvent[]
  latest: AlertEvent | null
  onShow: (alert: Alert) => void
}

/** Detail lu apres le libelle : « 1 critique, 2 avertissements ». */
function breakdown(active: Alert[]): string {
  const critical = active.filter((a) => a.severity === 'critical').length
  const warning = active.length - critical
  const parts: string[] = []
  if (critical) parts.push(plural(critical, 'critique'))
  if (warning) parts.push(plural(warning, 'avertissement'))
  return parts.join(', ')
}

/** Flux coupe sans alerte : coche neutre, « aucune alerte » n'est plus confirme. */
function chipLook(status: AlertsStatus, loaded: boolean, top: AlertSeverity | null, n: number):
  { icon: IconName; tone: Tone; label: string } {
  if (status === 'disabled') return { icon: 'bell-off', tone: 'muted', label: 'Alertes désactivées' }
  if (!loaded) return { icon: 'clock', tone: 'muted', label: 'Alertes : …' }
  if (top === null) {
    return { icon: 'check-circle', tone: status === 'disconnected' ? 'muted' : 'good', label: 'Aucune alerte' }
  }
  return { icon: top === 'critical' ? 'alert-octagon' : 'alert-triangle', tone: top, label: `Alertes : ${n}` }
}

/** Panneau non modal : ferme par Echap, clic exterieur, Fermer ou focus sorti.
 * Focus au panneau a l'ouverture, rendu a la puce apres une fermeture au clavier. */
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

  // Echap en capture : masque le raccourci global Echap tant que le panneau est ouvert
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

  // Focus sorti (Tab) : fermer, sinon le panneau masque la cible. Sans
  // relatedTarget (clic sur du texte du panneau), rien ne se ferme.
  const onBlur = (e: FocusEvent<HTMLDivElement>) => {
    const next = e.relatedTarget
    if (open && next instanceof Node && !e.currentTarget.contains(next)) setOpen(false)
  }

  const show = (alert: Alert) => {
    onShow(alert)
    close(true)
  }

  const n = active.length
  const { icon, tone, label } = chipLook(status, loaded, highestSeverity(active), n)
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
      {/* Evenements recus en direct seulement (pas le GET initial) */}
      <span className="sr-only" role="status" aria-live="polite">{live}</span>
    </div>
  )
}
