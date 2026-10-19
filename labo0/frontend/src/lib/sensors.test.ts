import { describe, expect, it } from 'vitest'
import type { SensorSeries } from '../types'
import { colorSlots, sensorNames } from './sensors'

const series = (metadata: SensorSeries['last']['metadata']): SensorSeries => ({ points: [], last: { metadata } })

describe('sensors', () => {
  it('stable 1-8 color slot per sensor', () => {
    const ids = Array.from({ length: 9 }, (_, i) => `n${i}`)
    expect(Object.values(colorSlots(ids))).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 1])
  })

  it('name: zone, else space, else node_id; shared zone disambiguated', () => {
    const sensors = {
      a: series({ zone: { label: 'Atrium' } }),
      b: series({ zone: { label: 'Atrium' } }),
      c: series({ space: { label: 'Salle 101' } }),
      d: series(undefined),
    }
    expect(sensorNames(sensors, ['a', 'b', 'c', 'd'])).toEqual({
      a: 'Atrium (a)', b: 'Atrium (b)', c: 'Salle 101', d: 'd',
    })
  })

  it('empty zone label: falls back to the space, like the backend', () => {
    const sensors = { a: series({ zone: { label: '' }, space: { label: 'Salle 101' } }), b: series({ zone: { label: '' } }) }
    expect(sensorNames(sensors, ['a', 'b'])).toEqual({ a: 'Salle 101', b: 'b' })
  })
})
