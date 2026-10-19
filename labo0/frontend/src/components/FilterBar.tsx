import { RangePicker } from './RangePicker'
import { SegmentedControl } from './SegmentedControl'
import type { SegmentOption } from './SegmentedControl'
import { SensorFilter } from './SensorFilter'
import { useMediaQuery } from '../hooks/useMediaQuery'
import type { TimeRange } from '../lib/ranges'
import type { ViewMode } from '../types'

/** Cibles de focus de repli (App) : dependent des data-focus-group ci-dessous. */
export const CHECKED_RANGE = '[data-focus-group="range"] [aria-checked="true"]'
export const CHECKED_VIEW = '[data-focus-group="view"] [aria-checked="true"]'

interface Props {
  range: TimeRange
  onRange: (r: TimeRange) => void
  sensorIds: string[]
  names: Record<string, string>
  slots: Record<string, number>
  sensor: string | null
  onSensor: (s: string | null) => void
  view: ViewMode
  onView: (v: ViewMode) => void
  disabled: boolean
}

const VIEW_OPTIONS: SegmentOption<ViewMode>[] = [
  { value: 'chart', label: 'Graphe', icon: 'chart-line', title: 'Raccourci v' },
  { value: 'table', label: 'Tableau', icon: 'table', title: 'Raccourci v' },
]

export function FilterBar({
  range, onRange, sensorIds, names, slots, sensor, onSensor, view, onView, disabled,
}: Props) {
  const stacked = !useMediaQuery('(min-width: 720px)')
  return (
    <div className="filterbar" role="group" aria-label="Filtres">
      <div className="filterbar__range" data-focus-group="range">
        <RangePicker selected={range} onSelect={onRange} grow={stacked} />
      </div>
      <div className={disabled ? 'filterbar__sensor filterbar__sensor--disabled' : 'filterbar__sensor'}>
        <SensorFilter
          sensorIds={sensorIds} names={names} slots={slots}
          selected={sensor} onSelect={onSensor} grow={stacked} disabled={disabled}
        />
      </div>
      <div className="filterbar__view" data-focus-group="view">
        <SegmentedControl<ViewMode>
          ariaLabel="Affichage" options={VIEW_OPTIONS} value={view} onChange={onView}
          grow={stacked} disabled={disabled}
        />
      </div>
    </div>
  )
}
