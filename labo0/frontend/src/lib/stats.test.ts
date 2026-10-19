import { describe, expect, it } from 'vitest'
import { anchorTime, freshness, medianInterval, mergeSeries, normalizePoints, seriesStats, sparkline, windowPoints } from './stats'

const pts = (...ts: number[]) => ts.map((t, i) => ({ t, v: i }))

describe('series', () => {
  it('already clean series: same reference', () => {
    const clean = pts(1, 2, 3)
    expect(normalizePoints(clean)).toBe(clean)
  })

  it('unordered series: sorted, last point for the same t wins', () => {
    const raw = [{ t: 3, v: 1 }, { t: 1, v: 2 }, { t: 3, v: 9 }]
    expect(normalizePoints(raw)).toEqual([{ t: 1, v: 2 }, { t: 3, v: 9 }])
  })

  it('window anchored on the latest sensor point', () => {
    const a = pts(0, 60_000, 120_000)
    expect(anchorTime({ a, b: pts(10) })).toBe(120_000)
    expect(windowPoints(a, 'all', 120_000)).toBe(a)
    expect(windowPoints(a, 60_000, 120_000).map((p) => p.t)).toEqual([60_000, 120_000])
  })

  it('single-pass statistics', () => {
    const stats = seriesStats([{ t: 1, v: 5 }, { t: 2, v: 2 }, { t: 3, v: 8 }])
    expect(stats).toMatchObject({ count: 3, first: 5, last: 8, min: 2, minT: 2, max: 8, maxT: 3, mean: 5, delta: 3 })
    expect(seriesStats([])).toBeNull()
  })

  it('sparkline: 12 buckets, empty buckets filled', () => {
    const spark = sparkline([{ t: 0, v: 1 }, { t: 12, v: 13 }])
    expect(spark).toHaveLength(12)
    expect(spark[0]).toBe(1)
    expect(spark[11]).toBe(13)
    expect(spark[5]).toBe(1)
  })
})

describe('mergeSeries', () => {
  it('one row per bucket, stamped with the oldest real measurement', () => {
    const rows = mergeSeries({ a: [{ t: 0, v: 1 }, { t: 6000, v: 2 }], b: [{ t: 1000, v: 10 }] }, ['a', 'b'], 3000)
    expect(rows).toEqual([{ t: 0, a: 1, b: 10 }, { t: 6000, a: 2 }])
  })

  it('no sensor: no row', () => {
    expect(mergeSeries({}, [])).toEqual([])
  })
})

describe('period and freshness', () => {
  it('median of the latest intervals, 60 s by default', () => {
    expect(medianInterval(pts(0, 6000))).toBe(60_000)
    expect(medianInterval(pts(0, 6000, 12_000, 18_000))).toBe(6000)
  })

  it('30 s and 120 s floors', () => {
    expect(freshness(25_000, 6000)).toBe('fresh')
    expect(freshness(60_000, 6000)).toBe('late')
    expect(freshness(200_000, 6000)).toBe('stale')
  })
})
