import { memo, useMemo, useRef, useState } from 'react'
import { EmptyState } from './EmptyState'
import { Icon } from './Icon'
import { SeriesKey } from './SeriesKey'
import { csvFilename, downloadText, toCsv } from '../lib/csv'
import { updateKeepingFocus } from '../lib/focus'
import { fmtCount, fmtDateTime, fmtDayTime, fmtTime, fmtValue, plural } from '../lib/format'
import { topicLabel } from '../lib/metrics'
import type { ChartRow } from '../types'

interface Props {
  rows: ChartRow[]
  ids: string[]
  names: Record<string, string>
  slots: Record<string, number>
  unit: string
  decimals: number
  topic: string
  rangeLabel: string
  longSpan: boolean
  onShowAll?: () => void
}

const PAGE = 300
/** Colonne de capteur (px) : en dessous, le cadre defile au lieu d'ecraser les colonnes. */
const COL_MIN = 96

export const DataTable = memo(function DataTable({
  rows, ids, names, slots, unit, decimals, topic, rangeLabel, longSpan, onShowAll,
}: Props) {
  const [limit, setLimit] = useState(PAGE)
  const regionRef = useRef<HTMLDivElement>(null)
  const shown = useMemo(() => {
    const out: ChartRow[] = []
    for (let i = rows.length - 1; i >= 0 && out.length < limit; i--) out.push(rows[i])
    return out
  }, [rows, limit])

  if (rows.length === 0) return <EmptyState kind="empty-range" onAction={onShowAll} />

  const exportCsv = () => {
    downloadText(csvFilename(topic, rangeLabel), toCsv(rows, ids, names, decimals))
  }

  return (
    <>
      <div className="datatable__bar">
        <p className="datatable__count">
          {shown.length < rows.length
            ? `${fmtCount(shown.length)} lignes sur ${fmtCount(rows.length)}`
            : plural(rows.length, 'ligne')}
          {/* Sous 720 px, l'ordre passe a la ligne, sans le point median */}
          <span className="datatable__sep"> · </span>
          <span className="datatable__order">plus récentes en haut</span>
        </p>
        <button
          type="button"
          className="btn"
          onClick={exportCsv}
          title="CSV ; séparateur point-virgule, décimale virgule, UTF-8"
        >
          <Icon name="download" size={14} />
          Exporter CSV
        </button>
      </div>
      <div ref={regionRef} className="datatable" role="region" tabIndex={0} aria-label="Tableau des mesures">
        <table
          className={longSpan ? 'datatable__table datatable__table--long' : 'datatable__table'}
          style={{ minWidth: `calc(var(--dt-time-w) + ${ids.length * COL_MIN}px)` }}
        >
          <caption className="sr-only">
            {topicLabel(topic)}{unit ? ` (${unit})` : ''} · {rangeLabel} · {rows.length} lignes
          </caption>
          <thead>
            <tr>
              <th scope="col">Horodatage</th>
              {ids.map((id) => (
                <th key={id} scope="col">
                  <SeriesKey slot={slots[id]} />
                  {/* Sans unite : elle est dans le titre de la carte et la caption */}
                  <span className="datatable__name" title={names[id]}>{names[id]}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((row) => (
              <tr key={row.t}>
                <td className="num" title={fmtDateTime(row.t)}>
                  {longSpan ? fmtDayTime(row.t, true) : fmtTime(row.t, true)}
                </td>
                {ids.map((id) => {
                  const v = row[id]
                  return <td key={id} className="num">{typeof v === 'number' ? fmtValue(v, decimals) : '—'}</td>
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {limit < rows.length && (
          <div className="datatable__more">
            {/* Derniere page : le bouton se retire, le focus passe au tableau */}
            <button
              type="button"
              className="btn"
              onClick={() => updateKeepingFocus(() => setLimit((l) => l + PAGE), () => regionRef.current)}
            >
              Afficher {PAGE} lignes de plus
            </button>
          </div>
        )}
      </div>
    </>
  )
})
