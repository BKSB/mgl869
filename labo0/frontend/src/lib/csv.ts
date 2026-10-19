/** Export CSV (Excel fr-CA : point-virgule, virgule decimale, BOM UTF-8). */

import type { ChartRow } from '../types'
import { fmtDateTime, roundsToZero } from './format'

/** Apostrophe devant = + - @, tabulation ou retour en tete, sinon Excel evalue
 * une formule (libelles Kafka : « -1 Sous-sol », « =HYPERLINK(…) »). */
function textField(s: string): string {
  const safe = /^[=+\-@\t\r]/.test(s) ? `'${s}` : s
  return /[;"\r\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe
}

/** Jamais « -0,0 », comme dans le tableau. */
const numberField = (v: number, decimals: number) =>
  (roundsToZero(v, decimals) ? 0 : v).toFixed(decimals).replace('.', ',')

/** Horodatage ISO local sans fuseau : « 2026-10-04T10:14:06 ». */
const isoLocal = (t: number) => fmtDateTime(t).replace(' ', 'T')

/** BOM UTF-8 en echappement explicite (un editeur pourrait retirer le
 * caractere invisible) : sans lui, Excel fr-CA lit le fichier en ANSI. */
export function toCsv(
  rows: ChartRow[],
  ids: string[],
  names: Record<string, string>,
  decimals: number,
): string {
  const head = ['horodatage', ...ids.map((id) => textField(`${names[id]} (${id})`))].join(';')
  const lines = rows.map((row) => {
    const cells = ids.map((id) => {
      const v = row[id]
      return typeof v === 'number' ? numberField(v, decimals) : ''
    })
    return [isoLocal(row.t), ...cells].join(';')
  })
  return `\uFEFF${[head, ...lines].join('\r\n')}\r\n`
}

export function downloadText(filename: string, text: string, mime = 'text/csv;charset=utf-8'): void {
  const url = URL.createObjectURL(new Blob([text], { type: mime }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** « gridd-temperature-15-min-2026-10-04T101406.csv » */
export function csvFilename(topic: string, rangeLabel: string, now = new Date()): string {
  const slug = rangeLabel.normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '').toLowerCase()
  // Heure locale, comme la colonne horodatage du fichier (jamais UTC)
  const stamp = fmtDateTime(now.getTime()).replace(' ', 'T').replace(/:/g, '')
  return `gridd-${topic.split('.').pop()}-${slug}-${stamp}.csv`
}
