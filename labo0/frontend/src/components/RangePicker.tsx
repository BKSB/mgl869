import { SegmentedControl } from './SegmentedControl'
import { RANGE_PRESETS } from '../lib/ranges'
import type { TimeRange } from '../lib/ranges'

interface Props {
  selected: TimeRange
  onSelect: (range: TimeRange) => void
  grow?: boolean
}

const OPTIONS = RANGE_PRESETS.map((p, i) => ({
  value: p.value,
  label: p.label,
  title: `Raccourci ${i + 1}`,
}))

export function RangePicker({ selected, onSelect, grow }: Props) {
  return (
    <SegmentedControl<TimeRange>
      ariaLabel="Plage temporelle"
      showCheck
      grow={grow}
      options={OPTIONS}
      value={selected}
      onChange={onSelect}
    />
  )
}
