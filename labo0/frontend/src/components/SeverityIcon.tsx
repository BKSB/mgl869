import { Icon } from './Icon'
import type { AlertSeverity } from '../types'

interface Props {
  severity: AlertSeverity
  size?: 12 | 14 | 16
  className?: string
}

/** Forme + couleur ; l'appelant fournit toujours un libelle (visible ou sr-only). */
export function SeverityIcon({ severity, size = 14, className }: Props) {
  const cls = `sev sev--${severity}${className ? ` ${className}` : ''}`
  return <Icon name={severity === 'critical' ? 'alert-octagon' : 'alert-triangle'} size={size} className={cls} />
}
