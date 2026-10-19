import { describe, expect, it } from 'vitest'
import { csvFilename, toCsv } from './csv'

const BOM = String.fromCharCode(0xfeff)

describe('toCsv', () => {
  const csv = toCsv([{ t: 0, a: -0.04, b: 1.25 }], ['a', 'b'], { a: '-1 Sous-sol', b: '=HYPERLINK("x";"y")' }, 1)
  const [head, line] = csv.slice(1).split('\r\n')

  it('UTF-8 BOM and CRLF line endings (Excel fr-CA)', () => {
    expect(csv.startsWith(BOM)).toBe(true)
    expect(csv.endsWith('\r\n')).toBe(true)
  })

  it('neutralizes formulas in the header', () => {
    expect(head).toBe(`horodatage;'-1 Sous-sol (a);"'=HYPERLINK(""x"";""y"") (b)"`)
  })

  it('decimal comma, never -0,0', () => {
    expect(line.endsWith(';0,0;1,3')).toBe(true)
  })
})

describe('csvFilename', () => {
  const now = new Date(2026, 9, 4, 10, 14, 6)

  it('last topic segment, range without accents, local time', () => {
    expect(csvFilename('gridd.obs.environmental.temperature', '15 min', now))
      .toBe('gridd-temperature-15-min-2026-10-04T101406.csv')
    expect(csvFilename('gridd.obs.environmental.co2', 'tout l’historique', now))
      .toBe('gridd-co2-tout-l-historique-2026-10-04T101406.csv')
  })
})
