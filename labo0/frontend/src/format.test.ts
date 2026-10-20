import { describe, expect, it } from 'vitest'
import { fmtAgo, fmtTime } from './format'

describe('fmtTime', () => {
  it('renders HH:mm:ss in local time', () => {
    expect(fmtTime(new Date(2026, 9, 20, 14, 32, 5).getTime())).toBe('14:32:05')
    expect(fmtTime(new Date(2026, 9, 20, 0, 0, 0).getTime())).toBe('00:00:00')
  })
})

describe('fmtAgo', () => {
  const now = 1_700_000_000_000

  it('scales from seconds to days', () => {
    expect(fmtAgo(now, now)).toBe('à l’instant')
    expect(fmtAgo(now + 5000, now)).toBe('à l’instant')
    expect(fmtAgo(now - 2000, now)).toBe('il y a 2 s')
    expect(fmtAgo(now - 59_400, now)).toBe('il y a 59 s')
    expect(fmtAgo(now - 3 * 60_000, now)).toBe('il y a 3 min')
    expect(fmtAgo(now - 2 * 3_600_000, now)).toBe('il y a 2 h')
    expect(fmtAgo(now - 3 * 86_400_000, now)).toBe('il y a 3 j')
  })
})
