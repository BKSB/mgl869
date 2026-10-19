import { describe, expect, it } from 'vitest'
import type { SensorSeries, SensorValue, TopicRecord } from '../types'
import { appendBatch, DISCONNECTED_TEXT, EMPTY_LABEL, emptyKind, MAX_POINTS, RECONNECT_TEXT } from './stream'

describe('stream states', () => {
  it('empty state reason', () => {
    expect(emptyKind(false, 'live', false)).toBeNull()
    expect(emptyKind(true, 'live', false)).toBe('replaying')
    expect(emptyKind(true, 'live', true)).toBe('waiting')
    expect(emptyKind(true, 'connecting', false)).toBe('connecting')
    expect(emptyKind(true, 'disconnected', false)).toBe('disconnected')
  })

  it('reconnection texts', () => {
    expect(RECONNECT_TEXT).toBe('reconnexion toutes les 3 s')
    expect(DISCONNECTED_TEXT).toBe(`${EMPTY_LABEL.disconnected} — reconnexion toutes les 3 s`)
  })
})

let offset = 0
const record = (sensor: string, t: number, value: TopicRecord['value']): TopicRecord => ({
  topic: 't', partition: 0, offset: offset++, timestamp_ms: t, key: null, value, sensor_id: sensor,
})
const measurement = (v: number, unit = 'ppm'): SensorValue => ({ node_id: 'x', value: v, unit })

describe('appendBatch', () => {
  it('groups by sensor_id, in arrival order, with the last payload', () => {
    const next = appendBatch({}, [
      record('a', 1, measurement(10)), record('b', 2, measurement(20)), record('a', 3, measurement(11, 'ppm2')),
    ])
    expect(next.a.points).toEqual([{ t: 1, v: 10 }, { t: 3, v: 11 }])
    expect(next.a.last.unit).toBe('ppm2')
    expect(next.b.points).toEqual([{ t: 2, v: 20 }])
  })

  it('extends existing series without touching other sensors', () => {
    const before: Record<string, SensorSeries> = {
      a: { points: [{ t: 0, v: 1 }], last: measurement(1) },
      b: { points: [{ t: 0, v: 5 }], last: measurement(5) },
    }
    const next = appendBatch(before, [record('a', 1, measurement(2))])
    expect(next.a.points).toEqual([{ t: 0, v: 1 }, { t: 1, v: 2 }])
    expect(next.b).toBe(before.b)
    expect(before.a.points).toHaveLength(1)
  })

  it('keeps the last MAX_POINTS points', () => {
    const batch = Array.from({ length: MAX_POINTS + 5 }, (_, i) => record('a', i, measurement(i)))
    const points = appendBatch({}, batch).a.points
    expect(points).toHaveLength(MAX_POINTS)
    expect(points[0].t).toBe(5)
  })

  it('ignores non-numeric records; batch without points: same reference', () => {
    const before: Record<string, SensorSeries> = {}
    const batch = [record('a', 1, 'texte brut'), record('a', 2, null), record('a', 3, { node_id: 'a' })]
    expect(appendBatch(before, batch)).toBe(before)
  })
})
