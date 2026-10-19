import { Icon } from './Icon'
import type { AlertSeverity } from '../types'

interface Props {
  severity: AlertSeverity
  size?: 12 | 14 | 16
  className?: string
}

/** Icone de severite : triangle ambre (avertissement), octogone rouge
 * (critique). Forme + couleur ; le libelle est toujours fourni a cote
 * (texte visible ou sr-only) : la couleur ne porte jamais le sens seule. */
export function SeverityIcon({ severity, size = 14, className }: Props) {
  const cls = `sev sev--${severity}${className ? ` ${className}` : ''}`
  return <Icon name={severity === 'critical' ? 'alert-octagon' : 'alert-triangle'} size={size} className={cls} />
}
