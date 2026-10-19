import { SegmentedControl } from './SegmentedControl'
import type { SegmentOption } from './SegmentedControl'
import type { ThemeMode } from '../types'

const OPTIONS: SegmentOption<ThemeMode>[] = [
  { value: 'system', label: 'Système', icon: 'monitor', iconOnly: true, title: 'Thème : système' },
  { value: 'light', label: 'Clair', icon: 'sun', iconOnly: true, title: 'Thème : clair' },
  { value: 'dark', label: 'Sombre', icon: 'moon', iconOnly: true, title: 'Thème : sombre' },
]

/** Bascule Systeme / Clair / Sombre (icones seules, libelles sr-only). */
export function ThemeToggle({ mode, onChange }: { mode: ThemeMode; onChange: (m: ThemeMode) => void }) {
  return <SegmentedControl<ThemeMode> size="sm" ariaLabel="Thème" options={OPTIONS} value={mode} onChange={onChange} />
}
