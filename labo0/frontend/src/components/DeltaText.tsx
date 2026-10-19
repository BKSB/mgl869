import { Icon } from './Icon'
import type { IconName } from './Icon'
import { fmtDelta, isStableDelta } from '../lib/format'
import type { Polarity } from '../types'

interface Props {
  delta: number
  unit: string
  decimals: number
  polarity: Polarity
  periodLabel: string
}

/** Variation sur la plage : la fleche seule porte la couleur de statut, le
 * texte reste en encre secondaire (contraste garanti dans les deux themes). */
export function DeltaText({ delta, unit, decimals, polarity, periodLabel }: Props) {
  const stable = isStableDelta(delta, decimals)
  const icon: IconName = stable ? 'arrow-right' : delta > 0 ? 'arrow-up' : 'arrow-down'
  const color = stable
    ? 'var(--muted)'
    : polarity === 'neutral'
      ? 'var(--text-secondary)'
      : delta > 0 ? 'var(--status-critical)' : 'var(--status-good)'
  return (
    <span className="delta">
      <span className="delta__icon" style={{ color }} aria-hidden="true">
        <Icon name={icon} size={12} />
      </span>
      <span className="delta__text">
        {stable
          ? 'stable'
          : <>{fmtDelta(delta, decimals, unit)} <span className="delta__period">{periodLabel}</span></>}
      </span>
    </span>
  )
}
