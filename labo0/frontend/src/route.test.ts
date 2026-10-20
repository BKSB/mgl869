import { describe, expect, it } from 'vitest'
import { chartHash, parseHash, roomHash, toHash } from './route'

describe('parseHash', () => {
  it('reads each view with its optional id', () => {
    expect(parseHash('#/rooms')).toEqual({ view: 'rooms' })
    expect(parseHash('#/rooms/salle-b')).toEqual({ view: 'rooms', room: 'salle-b' })
    expect(parseHash('#/metrics')).toEqual({ view: 'metric' })
    expect(parseHash('#/metrics/co2')).toEqual({ view: 'metric', metric: 'co2' })
    expect(parseHash('#/alerts')).toEqual({ view: 'alerts' })
    expect(parseHash('#/chart/co2/co2-b-01')).toEqual({ view: 'chart', metric: 'co2', sensor: 'co2-b-01' })
  })

  it('falls back to rooms', () => {
    expect(parseHash('')).toEqual({ view: 'rooms' })
    expect(parseHash('#')).toEqual({ view: 'rooms' })
    expect(parseHash('#/inconnu/x')).toEqual({ view: 'rooms', room: 'x' })
    expect(parseHash('#/chart/co2')).toEqual({ view: 'rooms' })
  })

  it('decodes ids and tolerates a malformed escape', () => {
    expect(parseHash('#/rooms/Salle%20B')).toEqual({ view: 'rooms', room: 'Salle B' })
    expect(parseHash('#/rooms/100%')).toEqual({ view: 'rooms', room: '100%' })
  })
})

describe('toHash', () => {
  it('round-trips with parseHash', () => {
    for (const hash of ['#/rooms', '#/rooms/salle%20b', '#/metrics', '#/metrics/co2', '#/alerts', '#/chart/co2/n%2F1']) {
      expect(toHash(parseHash(hash))).toBe(hash)
    }
    expect(roomHash('a/b')).toBe('#/rooms/a%2Fb')
    expect(chartHash('co2', 'a b')).toBe('#/chart/co2/a%20b')
  })
})
