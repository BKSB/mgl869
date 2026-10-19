import { describe, expect, it } from 'vitest'
import type { Alert, AlertEvent } from '../types'
import { alertText, announcement, applyEvent, eventKey, highestSeverity, resolutionText, sortAlerts } from './alerts'
import { NBSP, THIN } from './testing'

const base = { id: 'x|n1', node_id: 'n1', location: 'Zone A', since_ms: 1, updated_ms: 2, message: 'backend' }
const temp = (value: number): Alert => ({
  ...base, topic: 'gridd.obs.environmental.temperature', severity: 'warning', direction: 'above',
  threshold: 26, hysteresis: 0.5, unit: '°C', value,
})
const hum = (value: number): Alert => ({
  ...base, topic: 'gridd.obs.environmental.humidity', severity: 'warning', direction: 'above',
  threshold: 60, hysteresis: 2, unit: '%', value,
})
const co2 = (value: number): Alert => ({
  ...base, topic: 'gridd.obs.environmental.co2', severity: 'critical', direction: 'above',
  threshold: 1500, hysteresis: 50, unit: 'ppm', value,
})

describe('texts composed by the dashboard', () => {
  it('beyond the threshold, with the topic decimals', () => {
    expect(alertText(temp(27.25))).toBe(`Température au-dessus de 26${THIN}°C (27,3${THIN}°C)`)
    expect(alertText(hum(61.3))).toBe(`Humidité au-dessus de 60${THIN}% (61${THIN}%)`)
  })

  it('the value is never written like the threshold', () => {
    expect(alertText(temp(26.04))).toBe(`Température au-dessus de 26${THIN}°C (26,04${THIN}°C)`)
    expect(alertText(hum(60.4))).toBe(`Humidité au-dessus de 60${THIN}% (60,4${THIN}%)`)
  })

  it('alert held by hysteresis', () => {
    expect(alertText(co2(1460))).toBe(
      `CO₂ à 1${NBSP}460${THIN}ppm (seuil 1${NBSP}500${THIN}ppm), niveau critique maintenu jusqu’à 1${NBSP}450${THIN}ppm`)
    expect(alertText(temp(25.98))).toBe(
      `Température à 25,98${THIN}°C (seuil 26${THIN}°C), alerte maintenue jusqu’à 25,5${THIN}°C`)
  })

  it('resolution and announcement, without the backend message', () => {
    expect(resolutionText(temp(25.4))).toBe(`Température de nouveau sous 26${THIN}°C (25,4${THIN}°C)`)
    const event: AlertEvent = { kind: 'raised', at_ms: 2, alert: hum(61.3) }
    expect(announcement(event)).toBe(`Nouvel avertissement : Humidité au-dessus de 60${THIN}% (61${THIN}%), Zone A`)
    expect(alertText(hum(61.3))).not.toContain('backend')
  })
})

describe('active alerts list', () => {
  const a = (id: string, severity: Alert['severity'], since_ms: number): Alert => ({ ...co2(1600), id, severity, since_ms })

  it('critical first, then oldest, then id', () => {
    const sorted = sortAlerts([a('w1', 'warning', 1), a('c2', 'critical', 5), a('c1', 'critical', 5), a('c0', 'critical', 9)])
    expect(sorted.map((x) => x.id)).toEqual(['c1', 'c2', 'c0', 'w1'])
  })

  it('an event replaces the alert, resolved removes it', () => {
    const active = [a('x', 'warning', 1)]
    const escalated = applyEvent(active, { kind: 'escalated', at_ms: 3, alert: a('x', 'critical', 1) })
    expect(escalated.map((x) => x.severity)).toEqual(['critical'])
    expect(applyEvent(escalated, { kind: 'resolved', at_ms: 4, alert: a('x', 'critical', 1) })).toEqual([])
  })

  it('highest severity and event key', () => {
    expect(highestSeverity([])).toBeNull()
    expect(highestSeverity([a('x', 'warning', 1)])).toBe('warning')
    expect(highestSeverity([a('x', 'warning', 1), a('y', 'critical', 1)])).toBe('critical')
    expect(eventKey({ kind: 'raised', at_ms: 7, alert: a('x', 'warning', 1) })).toBe('raised|7|x')
  })
})
