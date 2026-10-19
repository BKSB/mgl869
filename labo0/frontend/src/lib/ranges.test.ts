import { describe, expect, it } from 'vitest'
import { deltaRangeLabel, rangeLabel, rangeTitle } from './ranges'

describe('ranges', () => {
  it('lowercase label', () => {
    expect(rangeLabel('all')).toBe('tout l’historique')
    expect(rangeLabel(15 * 60_000)).toBe('15 min')
    expect(rangeLabel(3 * 3_600_000)).toBe('3 h')
    expect(rangeLabel(2 * 3_600_000)).toBe('2 h')
    expect(rangeLabel(45 * 60_000)).toBe('45 min')
  })

  it('window title and delta period', () => {
    expect(rangeTitle('all')).toBe('Tout l’historique')
    expect(rangeTitle(3_600_000)).toBe('Dernière heure')
    expect(rangeTitle(15 * 60_000)).toBe('Dernières 15 min')
    expect(deltaRangeLabel('all')).toBe('l’historique')
    expect(deltaRangeLabel(3 * 3_600_000)).toBe('3 h')
  })
})
