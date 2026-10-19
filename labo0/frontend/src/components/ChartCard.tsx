import type { ReactNode } from 'react'
import { Icon } from './Icon'
import { LastUpdated } from './LastUpdated'
import { fmtTime } from '../lib/format'
import { DISCONNECTED_TEXT } from '../lib/stream'
import type { ConnectionStatus } from '../types'

interface Props {
  id: string
  title: string
  subtitle: string
  /** Chiffre heros (capteur isole) ; l'unite est rendue plus petite. */
  hero?: { value: string; unit?: string; caption: string }
  /** Fraicheur des capteurs affiches (celle du capteur isole s'il l'est). */
  lastT: number | undefined
  period: number
  /** « disconnected » pendant toute la coupure, tentatives comprises : le
   * bandeau role=alert reste en place (il n'est pas re-annonce a chaque
   * tentative). */
  status: ConnectionStatus
  replaying: boolean
  /** id de l'onglet actif ; sans onglet, la carte porte un aria-label. */
  labelledBy?: string
  children: ReactNode
}

/** Carte heros : bandeau d'alerte interne si le flux est coupe, en-tete
 * (titre, sous-titre, chiffre heros, mise a jour), corps flexible. */
export function ChartCard({
  id, title, subtitle, hero, lastT, period, status, replaying, labelledBy, children,
}: Props) {
  const disconnected = status === 'disconnected'
  const cls = ['card', 'hero', disconnected ? 'card--disconnected' : '', hero ? 'card--with-hero' : '']
    .filter(Boolean).join(' ')
  return (
    <section
      id={id}
      className={cls}
      role="tabpanel"
      aria-labelledby={labelledBy}
      aria-label={labelledBy ? undefined : 'Mesures'}
      aria-busy={replaying}
    >
      {disconnected && (
        <div className="card__banner" role="alert">
          <Icon name="alert-circle" size={14} />
          <span>
            {DISCONNECTED_TEXT}
            {lastT !== undefined && ` · dernières données : ${fmtTime(lastT, true)}`}
          </span>
        </div>
      )}
      {/* div et non header : dans un tabpanel, un header serait expose comme
          second landmark banner (celui de l'app bar suffit) */}
      <div className="card__head">
        <div className="card__titles">
          <h2 className="card__title">{title}</h2>
          <p className="card__sub">{subtitle}</p>
        </div>
        {hero && (
          <p className="card__hero">
            <strong>
              {hero.value}
              {hero.unit && <small>{hero.unit}</small>}
            </strong>
            <span>{hero.caption}</span>
          </p>
        )}
        <div className="card__meta">
          <LastUpdated t={lastT} period={period} />
        </div>
      </div>
      <div className="card__body">{children}</div>
    </section>
  )
}
