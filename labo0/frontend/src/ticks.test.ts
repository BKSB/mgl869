import { describe, expect, it } from 'vitest'
import { niceTicks, timeTicks } from './ticks'

describe('niceTicks', () => {
  it('uses round steps covering the domain', () => {
    expect(niceTicks(300, 1800)).toEqual([500, 750, 1000, 1250, 1500, 1750])
    expect(niceTicks(300, 1800, 4)).toEqual([500, 1000, 1500])
    expect(niceTicks(19.2, 27.1, 5)).toEqual([20, 22, 24, 26])
    expect(niceTicks(0, 1, 4)).toEqual([0, 0.25, 0.5, 0.75, 1])
  })

  it('handles a flat domain', () => {
    expect(niceTicks(5, 5)).toEqual([5])
  })
})

describe('timeTicks', () => {
  const day = 86_400_000
  const base = new Date(2026, 9, 9, 0, 0, 0).getTime()

  it('labels whole days at local midnight on long spans', () => {
    const ticks = timeTicks(base + 3_600_000, base + 7 * day)
    expect(ticks.map((t) => t.t)).toEqual([1, 2, 3, 4, 5, 6, 7].map((d) => new Date(2026, 9, 9 + d).getTime()))
    expect(ticks[0].label).toMatch(/10$/)
  })

  it('labels hours on short spans', () => {
    const ticks = timeTicks(base, base + 6 * 3_600_000)
    expect(ticks.map((t) => t.label)).toEqual(['00:00', '01:00', '02:00', '03:00', '04:00', '05:00', '06:00'])
  })

  it('keeps at most the requested count', () => {
    expect(timeTicks(base, base + 30 * day, 8).length).toBeLessThanOrEqual(8)
    expect(timeTicks(base, base, 8)).toEqual([])
  })
})
