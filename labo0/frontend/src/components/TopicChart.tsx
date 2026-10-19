import { memo, useMemo } from 'react'
import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { ChartTooltip } from './ChartTooltip'
import { useElementSize } from '../hooks/useElementSize'
import { fmtThreshold } from '../lib/alerts'
import type { SensorDerived } from '../hooks/useSeriesStats'
import { fmtDayTime, fmtTime, fmtValue, plural } from '../lib/format'
import { topicLabel } from '../lib/metrics'
import { rangeLabel } from '../lib/ranges'
import type { TimeRange } from '../lib/ranges'
import { xTicks, yLadder } from '../lib/ticks'
import type { YLadder } from '../lib/ticks'
import type { AlertRule, ChartRow } from '../types'

/** Axe Y (44) + marge droite (16). */
const PLOT_INSET_X = 60
/** Ecart min. entre libelles X (px), assez pour « 04 oct. 18:30 ». */
const X_LABEL_PX = 90
/** Hauteur de zone (px, axe X compris) par pas Y. */
const Y_TICK_PX = 48
const Y_TARGET_MIN = 4
const MARGIN = { top: 12, right: 16, bottom: 4, left: 0 }
/** Bande d'axe X (px) : ticks 11 px et leur marge. */
const X_AXIS_BAND = 30
/** Seuil a moins de 16 px du haut : etiquette sous la ligne (rognee sinon). */
const LABEL_FLIP_PX = 16
/** Recharts : entre la grille (-100) et les courbes (400) ; les Label restent a 2000. */
const THRESHOLD_Z = 350

/** Sans le mot « Seuil » : « critique 1 500 ppm », « bas d'avertissement 18 °C ». */
function thresholdDetail(rule: AlertRule, decimals: number, unit: string): string {
  const severity = rule.severity === 'critical' ? 'critique' : 'd’avertissement'
  const low = rule.direction === 'below' ? 'bas ' : ''
  return `${low}${severity} ${fmtThreshold(rule.threshold, decimals, unit)}`
}

interface Props {
  /** Deja fenetrees et fusionnees (useSeriesStats). */
  rows: ChartRow[]
  ids: string[]
  slots: Record<string, number>
  names: Record<string, string>
  byId: Record<string, SensorDerived>
  bucket: number
  unit: string
  decimals: number
  range: TimeRange
  longSpan: boolean
  /** Serie tracee ou null, filtre par App pour ne pas casser le memo. */
  hovered: string | null
  topicName: string
  /** Tracees si le seuil tombe dans l'echelle Y, jamais elargie pour un seuil. */
  rules: AlertRule[]
}

/** Clavier : accessibilityLayer (defaut Recharts 3), les fleches deplacent le curseur.
 * Graduations calculees (lib/ticks) : pas ronds en Y, horloge locale en X. */
export const TopicChart = memo(function TopicChart({
  rows, ids, slots, names, byId, bucket, unit, decimals, range, longSpan, hovered, topicName, rules,
}: Props) {
  // Taille de la zone : densite des graduations
  const [areaRef, { width, height }] = useElementSize<HTMLDivElement>()
  // yLadder etend le domaine jusqu'a la cible de pas : parmi les cibles que
  // permet la hauteur, garder celle ou les donnees remplissent le plus le domaine
  const ladder = useMemo(() => {
    let min = Infinity
    let max = -Infinity
    for (const id of ids) {
      const stats = byId[id]?.stats
      if (!stats) continue
      if (stats.min < min) min = stats.min
      if (stats.max > max) max = stats.max
    }
    const fill = (l: YLadder) => (max - min) / (l.domain[1] - l.domain[0] || 1)
    const maxTarget = Math.max(Y_TARGET_MIN, Math.floor(height / Y_TICK_PX))
    let best = yLadder(min, max, decimals, Y_TARGET_MIN)
    for (let target = Y_TARGET_MIN + 1; target <= maxTarget; target++) {
      const next = yLadder(min, max, decimals, target)
      if (fill(next) > fill(best) + 1e-9) best = next
    }
    return best
  }, [byId, ids, decimals, height])
  const t0 = rows[0]?.t
  const t1 = rows[rows.length - 1]?.t
  // Le pas garantit l'ecart entre libelles : preserveStartEnd + faible minTickGap
  // ne retire qu'un chevauchement et decale un libelle de bord au lieu de le rogner
  const maxTicksX = width > 0 ? Math.max(2, Math.floor((width - PLOT_INSET_X) / X_LABEL_PX)) : undefined
  const ticksX = useMemo(
    () => (t0 !== undefined && t1 !== undefined ? xTicks(t0, t1, maxTicksX) : []),
    [t0, t1, maxTicksX],
  )
  // Ticks a la minute ronde : les secondes seraient toujours « :00 »
  const tickFmt = useMemo(
    () => (t: number) => (longSpan ? fmtDayTime(t) : fmtTime(t, false)),
    [longSpan],
  )
  const yFmt = useMemo(() => (v: number) => fmtValue(v, ladder.decimals), [ladder.decimals])
  const thresholds = useMemo(() => {
    const [lo, hi] = ladder.domain
    const plotH = Math.max(0, height - MARGIN.top - MARGIN.bottom - X_AXIS_BAND)
    return rules
      .filter((r) => r.threshold >= lo && r.threshold <= hi)
      .map((rule) => ({
        rule,
        detail: thresholdDetail(rule, decimals, unit),
        below: hi > lo && ((hi - rule.threshold) / (hi - lo)) * plotH < LABEL_FLIP_PX,
      }))
  }, [rules, ladder.domain, height, decimals, unit])
  const thresholdsLabel = thresholds.length > 0
    ? ` ; seuils tracés : ${thresholds.map((t) => t.detail).join(', ')}`
    : ''

  return (
    <div
      ref={areaRef}
      className="chart-area"
      role="group"
      aria-label={`Graphique ${topicLabel(topicName)}, ${plural(ids.length, 'capteur')}, ${rangeLabel(range)}${thresholdsLabel} ; valeurs détaillées dans la vue Tableau`}
    >
      <ResponsiveContainer width="100%" height="100%" debounce={100}>
        <LineChart
          data={rows}
          margin={MARGIN}
          title={`Graphique ${topicLabel(topicName)}`}
          desc="Flèches gauche et droite : déplacer le curseur sur les mesures"
        >
          <CartesianGrid stroke="var(--gridline)" vertical={false} />
          <XAxis
            dataKey="t" type="number" scale="time" domain={['dataMin', 'dataMax']} ticks={ticksX}
            tickFormatter={tickFmt} interval="preserveStartEnd" minTickGap={8} stroke="var(--baseline)"
            tick={{ fill: 'var(--axis-text)', fontSize: 11 }} tickLine={false}
          />
          <YAxis
            domain={ladder.domain} ticks={ladder.ticks} width={44} stroke="transparent"
            tick={{ fill: 'var(--axis-text)', fontSize: 11 }} tickLine={false}
            tickFormatter={yFmt}
          />
          <Tooltip
            content={
              <ChartTooltip
                unit={unit} decimals={decimals} slots={slots} names={names}
                ids={ids} byId={byId} bucket={bucket} longSpan={longSpan}
              />
            }
            cursor={{ stroke: 'var(--baseline)', strokeWidth: 1 }}
            isAnimationActive={false}
            wrapperStyle={{ outline: 'none' }}
          />
          {thresholds.map(({ rule, detail, below }) => (
            <ReferenceLine
              key={`${rule.direction}-${rule.severity}-${rule.threshold}`}
              y={rule.threshold} ifOverflow="discard" zIndex={THRESHOLD_Z}
              stroke={`var(--status-${rule.severity})`} strokeWidth={1}
              strokeDasharray="4 4" strokeOpacity={0.7}
              label={{
                value: `Seuil ${detail}`,
                // Boite de hauteur nulle : insideBottom place le texte au-dessus, insideTop dessous
                position: below ? 'insideTopRight' : 'insideBottomRight',
                offset: 4,
                fill: 'var(--text-secondary)',
                fontSize: 11,
                // Halo couleur de surface : lisible meme sur une courbe
                stroke: 'var(--surface-1)',
                strokeWidth: 3,
                strokeLinejoin: 'round',
                paintOrder: 'stroke',
              }}
            />
          ))}
          {ids.map((id) => (
            <Line
              key={id} dataKey={id} name={names[id]} type="monotone" connectNulls
              stroke={`var(--series-${slots[id]})`} strokeWidth={2}
              strokeLinecap="round" strokeLinejoin="round"
              strokeOpacity={hovered !== null && hovered !== id ? 0.25 : 1}
              dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--surface-1)' }}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
})
