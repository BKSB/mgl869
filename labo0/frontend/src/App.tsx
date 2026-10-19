import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { fetchTopics } from './api/topics'
import { AppBar } from './components/AppBar'
import { ChartCard } from './components/ChartCard'
import { DataTable } from './components/DataTable'
import { EmptyState } from './components/EmptyState'
import { CHECKED_RANGE, CHECKED_VIEW, FilterBar } from './components/FilterBar'
import { LegendTable } from './components/LegendTable'
import { StatTileRow } from './components/StatTileRow'
import { TopicChart } from './components/TopicChart'
import { TOPIC_PANEL_ID, TopicTabs } from './components/TopicTabs'
import { useAlerts } from './hooks/useAlerts'
import { useHealth } from './hooks/useHealth'
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts'
import { useNow } from './hooks/useNow'
import { useSeriesStats } from './hooks/useSeriesStats'
import { useTheme } from './hooks/useTheme'
import { useTopicStream } from './hooks/useTopicStream'
import { updateKeepingFocus } from './lib/focus'
import { fmtDuration, fmtValue, plural } from './lib/format'
import { getTopicMeta, topicLabel } from './lib/metrics'
import { deltaRangeLabel, RANGE_PRESETS, rangeLabel, rangeTitle } from './lib/ranges'
import type { TimeRange } from './lib/ranges'
import { colorSlots, sensorNames } from './lib/sensors'
import { readStored, writeStored } from './lib/storage'
import { EMPTY_LABEL, emptyKind } from './lib/stream'
import { DAY } from './lib/time'
import type { Alert, AlertRule, ConnectionStatus, TopicInfo, ViewMode } from './types'
import './App.css'
import './components.css'

const VIEW_KEY = 'gridd.view'
/** Flux ouvert sans aucun message apres ce delai : le topic est muet. */
const WAITING_DELAY_MS = 8000
/** Cible du lien d'evitement et focus de repli : main est rendu meme en erreur. */
const MAIN_ID = 'contenu'
/** Topic sans regle d'alerte : reference stable (TopicChart est memo). */
const NO_RULES: AlertRule[] = []

/** Focus de repli quand une action demonte l'element focalise : bouton coche
 * du groupe, ou main si ce bouton est desactive. */
const checkedOr = (selector: string) => (): HTMLElement | null => {
  const next = document.querySelector<HTMLButtonElement>(selector)
  return next && !next.disabled ? next : document.getElementById(MAIN_ID)
}
const focusMain = () => document.getElementById(MAIN_ID)

const readStoredView = (): ViewMode => (readStored(VIEW_KEY) === 'table' ? 'table' : 'chart')

export default function App() {
  const [topics, setTopics] = useState<TopicInfo[]>([])
  const [topicsError, setTopicsError] = useState(false)
  // Distingue « chargement » de « liste vide »
  const [topicsLoaded, setTopicsLoaded] = useState(false)
  const [topic, setTopic] = useState<string | null>(null)
  // Capteur isole ; null : tous les capteurs
  const [sensor, setSensor] = useState<string | null>(null)
  const [range, setRange] = useState<TimeRange>('all')
  const [view, setView] = useState<ViewMode>(readStoredView)
  const [hovered, setHovered] = useState<string | null>(null)
  const [waitingTopic, setWaitingTopic] = useState<string | null>(null)

  const { sensors, status } = useTopicStream(topic)
  const { health, state: healthState } = useHealth()
  const alerts = useAlerts()
  const { mode: theme, setMode: setTheme } = useTheme()
  const now = useNow()

  const loadTopics = useCallback(() => {
    fetchTopics()
      .then((list) => {
        // Reessai reussi : le bouton focalise disparait, focus au main
        updateKeepingFocus(() => {
          setTopics(list)
          setTopicsError(false)
          setTopicsLoaded(true)
          setTopic((cur) => cur ?? list[0]?.name ?? null)
        }, focusMain)
      })
      .catch(() => setTopicsError(true))
  }, [])

  useEffect(() => {
    loadTopics()
  }, [loadTopics])

  useEffect(() => {
    writeStored(VIEW_KEY, view)
  }, [view])

  const noTopics = topicsLoaded && !topicsError && topics.length === 0
  const badgeStatus: ConnectionStatus | null = topicsError || noTopics ? null : status

  const sensorIds = useMemo(
    () => Object.keys(sensors).sort((a, b) => a.localeCompare(b, 'fr-CA', { numeric: true })),
    [sensors],
  )
  const slots = useMemo(() => colorSlots(sensorIds), [sensorIds])
  const names = useMemo(() => sensorNames(sensors, sensorIds), [sensors, sensorIds])
  const shownIds = useMemo(
    () => (sensor === null ? sensorIds : sensorIds.filter((id) => id === sensor)),
    [sensorIds, sensor],
  )
  // Filet de securite : survol d'un capteur absent ignore
  const hoveredId = hovered !== null && sensorIds.includes(hovered) ? hovered : null
  // Survol hors des series tracees -> null : le graphe (memo) n'est pas re-rendu
  const chartHover = hoveredId !== null && shownIds.includes(hoveredId) ? hoveredId : null
  const meta = getTopicMeta(topic)
  // References stables : LegendTable et TopicChart sont memo
  const sensorAlerts = alerts.bySensor(topic)
  const topicRules = (topic !== null && alerts.rules[topic]) || NO_RULES
  const unit = sensors[sensorIds[0]]?.last.unit ?? ''
  const { anchorT, byId, totalPoints, rows, firstT, lastT, period, bucket } =
    useSeriesStats(sensors, sensorIds, shownIds, range)

  // setState dans le minuteur, jamais dans le corps de l'effet
  const empty = sensorIds.length === 0
  useEffect(() => {
    if (!topic || status !== 'live' || !empty) return
    const timer = window.setTimeout(() => setWaitingTopic(topic), WAITING_DELAY_MS)
    return () => window.clearTimeout(timer)
  }, [topic, status, empty])
  const waiting = empty && status === 'live' && waitingTopic !== null && waitingTopic === topic
  // Raison de l'etat vide, calculee une fois : sous-titre, tiles et carte en derivent
  const emptyState = emptyKind(empty, status, waiting)

  const selectTopic = useCallback((name: string) => {
    setTopic(name)
    setSensor(null)
    setHovered(null)
    setWaitingTopic((w) => (w === name ? w : null)) // un autre topic repart en rejeu
  }, [])
  // Mises a jour groupees : ce setSensor l'emporte sur celui de selectTopic
  const showAlert = useCallback((alert: Alert) => {
    selectTopic(alert.topic)
    setSensor(alert.node_id)
  }, [selectTopic])
  const toggleSensor = useCallback((id: string) => setSensor((s) => (s === id ? null : id)), [])
  const showAllSensors = useCallback(() => setSensor(null), [])
  // La vue demontee ne recoit jamais son mouseleave : survol remis a zero
  const changeView = useCallback((v: ViewMode) => {
    setView(v)
    setHovered(null)
  }, [])
  const toggleView = useCallback(() => {
    // Contenu focalise demonte : focus au bouton de vue coche
    updateKeepingFocus(() => {
      setView((v) => (v === 'chart' ? 'table' : 'chart'))
      setHovered(null)
    }, checkedOr(CHECKED_VIEW))
  }, [])
  // « Afficher tout » disparait avec l'etat vide qui le porte
  const showAllRange = useCallback(() => {
    updateKeepingFocus(() => setRange('all'), checkedOr(CHECKED_RANGE))
  }, [])
  const selectRangeIndex = useCallback((i: number) => {
    const preset = RANGE_PRESETS[i]
    if (!preset) return
    // Une plage plus courte peut demonter le bouton « lignes de plus » du tableau
    updateKeepingFocus(() => setRange(preset.value), checkedOr(CHECKED_RANGE))
  }, [])

  useKeyboardShortcuts({ onRange: selectRangeIndex, onToggleView: toggleView, onEscape: showAllSensors })

  const title = topic ? (unit ? `${topicLabel(topic)} · ${unit}` : topicLabel(topic)) : 'Mesures'
  const span = range === 'all' && firstT !== undefined ? ` (${fmtDuration(anchorT - firstT)})` : ''
  const subtitle = emptyState
    ? EMPTY_LABEL[emptyState]
    : `${rangeTitle(range)}${span} · ${plural(shownIds.length, 'capteur')} · ${plural(totalPoints, 'point')}`
  // Historique affiche > 24 h : l'heure seule serait ambigue (axe, infobulle, tableau)
  const longSpan = rows.length > 1 && rows[rows.length - 1].t - rows[0].t > DAY
  const heroStats = sensor !== null ? byId[sensor]?.stats : undefined
  const hero = sensor !== null && heroStats
    ? { value: fmtValue(heroStats.last, meta.decimals), unit, caption: names[sensor] }
    : undefined

  let body: ReactNode
  if (emptyState) {
    body = <EmptyState kind={emptyState} />
  } else if (view === 'table') {
    body = (
      <DataTable
        key={topic}
        rows={rows} ids={shownIds} names={names} slots={slots}
        unit={unit} decimals={meta.decimals} topic={topic ?? ''} rangeLabel={rangeLabel(range)}
        longSpan={longSpan} onShowAll={showAllRange}
      />
    )
  } else {
    body = (
      <>
        {rows.length === 0 ? (
          <EmptyState kind="empty-range" onAction={showAllRange} />
        ) : (
          <TopicChart
            rows={rows} ids={shownIds} slots={slots} names={names} byId={byId} bucket={bucket}
            unit={unit} decimals={meta.decimals} range={range} longSpan={longSpan}
            hovered={chartHover} topicName={topic ?? ''} rules={topicRules}
          />
        )}
        <LegendTable
          sensorIds={sensorIds} sensors={sensors} slots={slots} names={names} byId={byId}
          unit={unit} decimals={meta.decimals} selected={sensor} hovered={hoveredId} alerts={sensorAlerts} now={now}
          onToggle={toggleSensor} onHover={setHovered}
        />
      </>
    )
  }

  return (
    <>
      <a className="skip-link" href={`#${MAIN_ID}`}>Aller au contenu</a>
      <div className="shell">
        <AppBar
          status={badgeStatus} health={health} healthState={healthState}
          topics={topics} alerts={alerts} onShowAlert={showAlert} theme={theme} onTheme={setTheme}
        />
        {/* tabIndex -1 : focalisable par script seulement (lien d'evitement).
            L'id du tabpanel (TOPIC_PANEL_ID) reste sur la carte. */}
        <main id={MAIN_ID} className="shell__main" tabIndex={-1}>
          {topicsError ? (
            <EmptyState kind="api-error" onAction={loadTopics} />
          ) : noTopics ? (
            <EmptyState kind="no-topics" onAction={loadTopics} />
          ) : (
            <>
              <TopicTabs
                topics={topics} selected={topic} onSelect={selectTopic}
                consumers={health?.consumers} alertsByTopic={alerts.byTopic}
              />
              <FilterBar
                range={range} onRange={setRange}
                sensorIds={sensorIds} names={names} slots={slots}
                sensor={sensor} onSensor={setSensor}
                view={view} onView={changeView}
                disabled={empty}
              />
              <StatTileRow
                sensorIds={sensorIds} sensors={sensors} names={names} slots={slots} byId={byId}
                unit={unit} decimals={meta.decimals} polarity={meta.polarity} rangeLabel={deltaRangeLabel(range)}
                selected={sensor} hovered={hoveredId} alerts={sensorAlerts} emptyKind={emptyState}
                onToggle={toggleSensor} onHover={setHovered}
              />
              <ChartCard
                id={TOPIC_PANEL_ID}
                title={title}
                subtitle={subtitle}
                hero={hero}
                lastT={lastT}
                period={period}
                status={status}
                replaying={emptyState === 'replaying'}
                labelledBy={topic ? `tab-${topic}` : undefined}
              >
                {body}
              </ChartCard>
            </>
          )}
        </main>
      </div>
    </>
  )
}
