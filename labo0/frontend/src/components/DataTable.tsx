import { memo, useMemo, useRef, useState } from 'react'
import { EmptyState } from './EmptyState'
import { Icon } from './Icon'
import { csvFilename, downloadText, toCsv } from '../lib/csv'
import { updateKeepingFocus } from '../lib/focus'
import { fmtCount, fmtDateTime, fmtDayTime, fmtTime, fmtValue } from '../lib/format'
import { topicLabel } from '../lib/labels'
import type { ChartRow } from '../types'

interface Props {
  /** Memes lignes que le graphe (meme plage, memes capteurs). */
  rows: ChartRow[]
  ids: string[]
  names: Record<string, string>
  slots: Record<string, number>
  unit: string
  decimals: number
  topic: string
  rangeLabel: string
  /** Historique affiche > 24 h : horodatages avec la date. */
  longSpan: boolean
  /** Plage vide : bascule sur tout l'historique. */
  onShowAll?: () => void
}

const PAGE = 300
/** Largeur minimale d'une colonne de capteur (px) : sous cette largeur, le
 * tableau defile horizontalement dans son cadre au lieu d'ecraser les colonnes. */
const COL_MIN = 96

/** Vue tableau jumelle du graphe : plus recentes en haut, 300 lignes par
 * page, export CSV fr-CA. */
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

  if (rows.length === 0) return <EmptyState kind="empty-range" onShowAll={onShowAll} />

  const exportCsv = () => {
    downloadText(csvFilename(topic, rangeLabel), toCsv(rows, ids, names, decimals))
  }

  return (
    <>
      <div className="datatable__bar">
        <p className="datatable__count">
          {shown.length < rows.length
            ? `${fmtCount(shown.length)} lignes sur ${fmtCount(rows.length)}`
            : `${fmtCount(rows.length)} ligne${rows.length > 1 ? 's' : ''}`}
          {/* Sous 720 px, l'ordre passe sur sa propre ligne (sans le point
              median) au lieu d'etre tronque */}
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
        {/* Colonnes de capteur de largeur egale (table-layout: fixed) */}
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
                  <span className="key" style={{ background: `var(--series-${slots[id] ?? 1})` }} aria-hidden="true" />
                  {/* Une seule ligne : nom tronque (complet en title) ; l'unite
                      est dans le titre de la carte et la legende du tableau */}
                  <span className="datatable__name" title={names[id] ?? id}>{names[id] ?? id}</span>
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
