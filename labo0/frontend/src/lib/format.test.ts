import { describe, expect, it } from 'vitest'
import { deltaLabel, fmtCount, fmtDayTime, fmtDelta, fmtDuration, fmtTime, fmtValue, isStableDelta, plural } from './format'
import { MINUS, NBSP, THIN } from './testing'

describe('fmtValue', () => {
  it('decimal comma, thin space before the unit, non-breaking thousands', () => {
    expect(fmtValue(22.44, 1, '°C')).toBe(`22,4${THIN}°C`)
    expect(fmtValue(1042, 0, 'ppm')).toBe(`1${NBSP}042${THIN}ppm`)
    expect(fmtValue(17.5, 1)).toBe('17,5')
  })

  it('true minus sign, never -0', () => {
    expect(fmtValue(-2.5, 1)).toBe(`${MINUS}2,5`)
    expect(fmtValue(-0.04, 1)).toBe('0,0')
  })
})

describe('delta', () => {
  it('sign except for zero', () => {
    expect(fmtDelta(0.3, 1, '°C')).toBe(`+0,3${THIN}°C`)
    expect(fmtDelta(-12, 0, 'ppm')).toBe(`${MINUS}12${THIN}ppm`)
  })

  it('stable below half of the last displayed digit', () => {
    expect(isStableDelta(0.04, 1)).toBe(true)
    expect(isStableDelta(0.05, 1)).toBe(false)
    expect(deltaLabel(0.04, 1, '°C', 'sur 15 min')).toBe('stable')
    expect(deltaLabel(0.3, 1, '°C', 'sur 15 min')).toBe(`+0,3${THIN}°C sur 15 min`)
  })
})

describe('times and durations', () => {
  const t = new Date(2026, 9, 4, 9, 5, 7).getTime()

  it('zero-padded local time, with or without seconds', () => {
    expect(fmtTime(t, true)).toBe('09:05:07')
    expect(fmtTime(t, false)).toBe('09:05')
    expect(fmtDayTime(t)).toBe('04 oct. 09:05')
    expect(fmtDayTime(t, true)).toBe('04 oct. 09:05:07')
  })

  it('elapsed duration', () => {
    expect(fmtDuration(30_000)).toBe('30 s')
    expect(fmtDuration(45 * 60_000)).toBe('45 min')
    expect(fmtDuration(3 * 3_600_000)).toBe('3 h')
    expect(fmtDuration(2 * 3_600_000 + 58 * 60_000)).toBe('2 h 58')
  })

  it('count with thousands separator', () => {
    expect(fmtCount(1842)).toBe(`1${NBSP}842`)
  })

  it('count and agreeing noun (0 and 1 are singular)', () => {
    expect(plural(0, 'capteur')).toBe('0 capteur')
    expect(plural(1, 'point')).toBe('1 point')
    expect(plural(1842, 'point')).toBe(`1${NBSP}842 points`)
    expect(plural(3, 'alerte active', 'alertes actives')).toBe('3 alertes actives')
  })
})
