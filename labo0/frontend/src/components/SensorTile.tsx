import type { ReactNode } from 'react'
import { fmtAgo } from '../format'
import type { SensorTile as Tile } from '../types'
import { Sparkline } from './Sparkline'
import { StatusBadge } from './StatusBadge'

interface Props {
  tile: Tile
  title: string
  subtitle: ReactNode
  footer: ReactNode
  now: number
  /** Tuile cliquable (vue Par capteur : vers la piece). */
  href?: string
}

export function SensorTile({ tile, title, subtitle, footer, now, href }: Props) {
  const body = (
    <>
      <header className="tile-head">
        <div className="tile-heading">
          <h3 className="tile-title">{title}</h3>
          <div className="tile-sub">{subtitle}</div>
        </div>
        <StatusBadge status={tile.status} label={tile.status_label} />
      </header>
      <div className="tile-value">
        <span className={`tile-number text-${tile.status}`}>{tile.value_text}</span>
        {tile.unit && <span className="tile-unit">{tile.unit}</span>}
      </div>
      <Sparkline points={tile.points} thresholds={tile.thresholds} status={tile.status} />
      <footer className="tile-foot">
        <span className="tile-note">{footer}</span>
        <span className="tile-ago">{fmtAgo(tile.updated_ms, now)}</span>
      </footer>
    </>
  )
  const className = `tile tile--${tile.status}`
  return href ? (
    <a className={`${className} tile--link`} href={href}>
      {body}
    </a>
  ) : (
    <article className={className}>{body}</article>
  )
}
