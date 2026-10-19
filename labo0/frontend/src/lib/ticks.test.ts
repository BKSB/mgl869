import { describe, expect, it } from 'vitest'
import { xTicks, yLadder } from './ticks'

describe('yLadder', () => {
  it.each([
    [3.4028235e38, 0], [3.4028235e38, 1], [2 ** 54, 0], [1e20, 0], [-1e20, 1], [22.4, 1], [0, 0],
  ])('terminates on a constant series (%s, %i decimal(s))', (v, decimals) => {
    const ladder = yLadder(v, v, decimals, 4)
    expect(ladder.ticks.length).toBeGreaterThanOrEqual(2)
    expect(ladder.domain[0]).toBeLessThanOrEqual(v)
    expect(ladder.domain[1]).toBeGreaterThanOrEqual(v)
  })

  it('nice step and at least `target` steps', () => {
    const ladder = yLadder(18.2, 22.4, 1, 4)
    expect(ladder.ticks).toEqual([18, 20, 22, 24, 26])
    expect(ladder.decimals).toBe(0)
  })

  it('a positive domain never goes below zero', () => {
    expect(yLadder(0, 3, 0, 4).domain[0]).toBe(0)
  })
})

describe('xTicks', () => {
  it('step < 1 h: epoch multiples within [t0, t1]', () => {
    const ticks = xTicks(30_000, 630_000, 10)
    expect(ticks).toEqual(Array.from({ length: 10 }, (_, i) => (i + 1) * 60_000))
  })

  it('zero span: no ticks', () => {
    expect(xTicks(1000, 1000)).toEqual([])
  })
})
