import { memo, useMemo } from 'react'
import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { ChartTooltip } from './ChartTooltip'
import { useElementSize } from '../hooks/useElementSize'
import { fmtThreshold } from '../lib/alerts'
import type { SensorDerived } from '../hooks/useSeriesStats'
import { fmtDayTime, fmtTime, fmtValue } from '../lib/format'
import { topicLabel } from '../lib/labels'
import { rangeLabel } from '../lib/ranges'
import type { TimeRange } from '../lib/ranges'
import { xTicks, yLadder } from '../lib/ticks'
import type { YLadder } from '../lib/ticks'
import type { AlertRule, ChartRow } from '../types'

/** Largeur reservee a l'axe Y (44) et a la marge droite (16) : reste le trace. */
const PLOT_INSET_X = 60
/** Ecart minimal entre deux libelles X (« 18:30 », « 04 oct. 18:30 »). */
const X_LABEL_PX = 90
/** Hauteur de zone par pas Y vise (bande d'axe X comprise). */
const Y_TICK_PX = 48
const Y_TARGET_MIN = 4
const MARGIN = { top: 12, right: 16, bottom: 4, left: 0 }
/** Hauteur de la bande d'axe X (ticks 11 px et leur marge), hors trace. */
const X_AXIS_BAND = 30
/** Seuil a moins de 16 px du haut du trace : etiquette sous la ligne (elle
 * serait rognee au-dessus). */
const LABEL_FLIP_PX = 16
/** Seuils sous les courbes (Line : 400), au-dessus de la grille (-100). Les
 * etiquettes gardent le calque par defaut des Label (2000) : lisibles. */
const THRESHOLD_Z = 350

/** « Seuil critique 1 500 ppm », « Seuil bas d’avertissement 18 °C ». */
function thresholdText(rule: AlertRule, decimals: number, unit: string): string {
  const severity = rule.severity === 'critical' ? 'critique' : 'd’avertissement'
  const low = rule.direction === 'below' ? 'bas ' : ''
  return `Seuil ${low}${severity} ${fmtThreshold(rule.threshold, decimals, unit)}`
}

interface Props {
  /** Lignes larges deja fenetrees et fusionnees (useSeriesStats). */
  rows: ChartRow[]
  /** Capteurs traces, dans l'ordre. */
  ids: string[]
  slots: Record<string, number>
  names: Record<string, string>
  byId: Record<string, SensorDerived>
  /** Seau de regroupement des lignes (ms). */
  bucket: number
  unit: string
  decimals: number
  range: TimeRange
  /** Historique affiche > 24 h : ticks et infobulle avec la date. */
  longSpan: boolean
  /** Capteur survole (tile ou legende) PARMI les series tracees : les autres
   * passent a .25 ; null, rien n'est attenue. App filtre deja : en mode
   * isole, survoler un autre capteur laisse cette prop a null et le graphe
   * (memo) n'est pas re-rendu. */
  hovered: string | null
  topicName: string
  /** Regles d'alerte du topic : une ligne de seuil pointillee par regle
   * dont le seuil tombe dans l'echelle Y (jamais elargie pour un seuil). */
  rules: AlertRule[]
}

/**
 * Le grand graphe du topic. Lignes 2 px, grille hairline solide, crosshair
 * solide, infobulle personnalisee ; accessibilityLayer (defaut Recharts 3) :
 * le focus + fleches deplacent le curseur au clavier. Les graduations sont
 * calculees a la main (lib/ticks) : pas « propres » sur Y, horloge locale sur X.
 */
export const TopicChart = memo(function TopicChart({
  rows, ids, slots, names, byId, bucket, unit, decimals, range, longSpan, hovered, topicName, rules,
}: Props) {
  // Taille de la zone du graphe : densite des graduations ({ 0, 0 } avant la
  // premiere mesure, qui arrive avant la premiere peinture)
  const [areaRef, { width, height }] = useElementSize<HTMLDivElement>()
  // Etendue Y = min / max (stats de la fenetre) des seules series tracees.
  // Cible de 4 pas au moins, plus si la hauteur le permet (un pas tous les
  // 48 px) ; yLadder complete le domaine jusqu'a la cible, donc une cible
  // haute peut l'elargir : on garde l'echelle ou les donnees occupent la plus
  // grande part du domaine (la plus petite cible a egalite).
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
  // Nombre de ticks X selon la largeur du trace : l'ecart entre libelles est
  // garanti par le pas choisi, Recharts les affiche donc tous
  // (preserveStartEnd + petit ecart : il ne retire qu'un libelle qui en
  // chevaucherait un autre, et decale vers l'interieur un libelle de bord au
  // lieu de le rogner)
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
  // Seuils visibles : dans le domaine Y calcule (ifOverflow « discard » ne
  // trace de toute facon rien au-dela) ; etiquette sous la ligne si elle est
  // collee au haut du trace
  const thresholds = useMemo(() => {
    const [lo, hi] = ladder.domain
    const plotH = Math.max(0, height - MARGIN.top - MARGIN.bottom - X_AXIS_BAND)
    return rules
      .filter((r) => r.threshold >= lo && r.threshold <= hi)
      .map((rule) => ({
        rule,
        text: thresholdText(rule, decimals, unit),
        below: hi > lo && ((hi - rule.threshold) / (hi - lo)) * plotH < LABEL_FLIP_PX,
      }))
  }, [rules, ladder.domain, height, decimals, unit])
  const thresholdsLabel = thresholds.length > 0
    ? ` ; seuils tracés : ${thresholds.map((t) => t.text.replace(/^Seuil /, '')).join(', ')}`
    : ''

  return (
    <div
      ref={areaRef}
      className="chart-area"
      role="group"
      aria-label={`Graphique ${topicLabel(topicName)}, ${ids.length} capteur(s), ${rangeLabel(range)}${thresholdsLabel} ; valeurs détaillées dans la vue Tableau`}
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
          {thresholds.map(({ rule, text, below }) => (
            <ReferenceLine
              key={`${rule.direction}-${rule.severity}-${rule.threshold}`}
              y={rule.threshold} ifOverflow="discard" zIndex={THRESHOLD_Z}
              stroke={`var(--status-${rule.severity})`} strokeWidth={1}
              strokeDasharray="4 4" strokeOpacity={0.7}
              label={{
                value: text,
                // Boite de hauteur nulle : « insideBottom » place le texte
                // au-dessus de la ligne, « insideTop » en dessous
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
              key={id} dataKey={id} name={names[id] ?? id} type="monotone" connectNulls
              stroke={`var(--series-${slots[id] ?? 1})`} strokeWidth={2}
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
