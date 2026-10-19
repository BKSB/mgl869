import { SegmentedControl } from './SegmentedControl'
import { RANGE_PRESETS } from '../lib/ranges'
import type { TimeRange } from '../lib/ranges'

export type { TimeRange } from '../lib/ranges'

interface Props {
  selected: TimeRange
  onSelect: (range: TimeRange) => void
  grow?: boolean
}

const OPTIONS = RANGE_PRESETS.map((p, i) => ({
  value: String(p.value),
  label: p.label,
  title: `Raccourci ${i + 1}`,
}))

/** Preselections de plage temporelle (fenetre glissante, coche 16 px). */
export function RangePicker({ selected, onSelect, grow }: Props) {
  return (
    <SegmentedControl<string>
      ariaLabel="Plage temporelle"
      showCheck
      grow={grow}
      options={OPTIONS}
      value={String(selected)}
      onChange={(v) => onSelect(v === 'all' ? 'all' : Number(v))}
    />
  )
}
