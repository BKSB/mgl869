import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { fetchTopics } from './api/topics'
import { AppBar } from './components/AppBar'
import { ChartCard } from './components/ChartCard'
import { DataTable } from './components/DataTable'
import { EmptyState } from './components/EmptyState'
import { FilterBar } from './components/FilterBar'
import { LegendTable } from './components/LegendTable'
import { StatTileRow } from './components/StatTileRow'
import { TopicChart } from './components/TopicChart'
import { TopicTabs } from './components/TopicTabs'
import { useAlerts } from './hooks/useAlerts'
import { useHealth } from './hooks/useHealth'
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts'
import { useNow } from './hooks/useNow'
import { useSeriesStats } from './hooks/useSeriesStats'
import { useTheme } from './hooks/useTheme'
import { useTopicStream } from './hooks/useTopicStream'
import { updateKeepingFocus } from './lib/focus'
import { fmtCount, fmtDuration, fmtValue } from './lib/format'
import { topicLabel } from './lib/labels'
import { getTopicMeta } from './lib/metrics'
import { RANGE_PRESETS, rangeLabel } from './lib/ranges'
import type { TimeRange } from './lib/ranges'
import { colorSlots, sensorNames } from './lib/sensors'
import { EMPTY_LABEL, emptyKind } from './lib/stream'
import type { Alert, AlertRule, ConnectionStatus, TopicInfo, ViewMode } from './types'
import './App.css'
import './components.css'

const VIEW_KEY = 'gridd.view'
const ONE_HOUR = 60 * 60_000
const ONE_DAY = 24 * ONE_HOUR
/** Flux ouvert sans aucun message apres ce delai : le topic est muet. */
const WAITING_DELAY_MS = 8000
/** Landmark main, cible du lien d'evitement (toujours rendu, meme en erreur). */
const MAIN_ID = 'contenu'
/** Boutons coches de la barre de filtres : plage (premier groupe) et vue. */
const CHECKED_RANGE = '.filterbar > [role="radiogroup"] [role="radio"][aria-checked="true"]'
const CHECKED_VIEW = '.filterbar__view [role="radio"][aria-checked="true"]'
/** Topic sans regle d'alerte : reference stable (TopicChart est memo). */
const NO_RULES: AlertRule[] = []

/** Cible du focus quand une action demonte l'element focalise (raccourci v
 * ou 1 a 4, « Afficher tout ») : le bouton coche d'un groupe de la barre de
 * filtres, ou le landmark main si ce bouton est desactive. */
const checkedOr = (selector: string) => (): HTMLElement | null => {
  const next = document.querySelector<HTMLButtonElement>(selector)
  return next && !next.disabled ? next : document.getElementById(MAIN_ID)
}
const focusMain = () => document.getElementById(MAIN_ID)

function readStoredView(): ViewMode {
  try {
    return localStorage.getItem(VIEW_KEY) === 'table' ? 'table' : 'chart'
  } catch {
    return 'chart'
  }
}

export default function App() {
  const [topics, setTopics] = useState<TopicInfo[]>([])
  const [topicsError, setTopicsError] = useState(false)
  // /api/topics a repondu au moins une fois (distingue « chargement » de « liste vide »)
  const [topicsLoaded, setTopicsLoaded] = useState(false)
  const [topic, setTopic] = useState<string | null>(null)
  const [sensor, setSensor] = useState<string | 'all'>('all')
  const [range, setRange] = useState<TimeRange>('all')
  const [view, setView] = useState<ViewMode>(readStoredView)
  const [hovered, setHovered] = useState<string | null>(null)
  // Topic pour lequel le delai d'attente s'est ecoule sans aucune donnee
  const [waitingTopic, setWaitingTopic] = useState<string | null>(null)

  // « connecting » tant qu'aucun flux n'a repondu (et sans topic) : jamais de
  // fausse coupure au chargement
  const { sensors, status } = useTopicStream(topic)
  const { health, state: healthState } = useHealth()
  const alerts = useAlerts()
  const { mode: theme, setMode: setTheme } = useTheme()
  const now = useNow()

  const loadTopics = useCallback(() => {
    fetchTopics()
      .then((list) => {
        // « Réessayer » reussi : l'etat d'erreur et son bouton focalise sont
        // remplaces par les onglets, le focus passe au landmark main
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
    try {
      localStorage.setItem(VIEW_KEY, view)
    } catch {
      // stockage indisponible : la vue vaut pour la session
    }
  }, [view])

  // Liste de topics vide ou en erreur : aucun flux a montrer, pas de badge
  const noTopics = topicsLoaded && !topicsError && topics.length === 0
  const badgeStatus: ConnectionStatus | null = topicsError || noTopics ? null : status

  // Derives purs : tri naturel des node_id, couleurs et noms stables
  const sensorIds = useMemo(
    () => Object.keys(sensors).sort((a, b) => a.localeCompare(b, 'fr-CA', { numeric: true })),
    [sensors],
  )
  const slots = useMemo(() => colorSlots(sensorIds), [sensorIds])
  const names = useMemo(() => sensorNames(sensors, sensorIds), [sensors, sensorIds])
  const shownIds = useMemo(
    () => (sensor === 'all' ? sensorIds : sensorIds.filter((id) => id === sensor)),
    [sensorIds, sensor],
  )
  // Filet de securite : un survol ne compte que s'il designe un capteur affiche
  const hoveredId = hovered !== null && sensorIds.includes(hovered) ? hovered : null
  // Le graphe n'attenue que s'il trace le capteur survole : en mode isole, le
  // survol d'un autre capteur laisse sa prop a null (pas de re-rendu)
  const chartHover = hoveredId !== null && shownIds.includes(hoveredId) ? hoveredId : null
  const meta = getTopicMeta(topic)
  // Alertes actives du topic par capteur et regles (references stables)
  const sensorAlerts = alerts.bySensor(topic)
  const topicRules = (topic !== null && alerts.rules[topic]) || NO_RULES
  const unit = sensors[sensorIds[0]]?.last.unit ?? ''
  const { anchorT, byId, totalPoints, rows, lastT, period, bucket } = useSeriesStats(sensors, sensorIds, shownIds, range)

  // Topic muet : flux ouvert mais aucun message apres WAITING_DELAY_MS. Le
  // setState passe par le minuteur (asynchrone), jamais dans le corps de l'effet.
  const empty = sensorIds.length === 0
  useEffect(() => {
    if (!topic || status !== 'live' || !empty) return
    const timer = window.setTimeout(() => setWaitingTopic(topic), WAITING_DELAY_MS)
    return () => window.clearTimeout(timer)
  }, [topic, status, empty])
  const waiting = empty && status === 'live' && waitingTopic !== null && waitingTopic === topic
  // Raison de l'etat vide, calculee une fois : sous-titre, tiles, corps et
  // aria-busy de la carte en derivent (memes mots partout)
  const emptyState = emptyKind(empty, status, waiting)

  const selectTopic = useCallback((name: string) => {
    setTopic(name)
    setSensor('all') // nouveau topic = nouveaux capteurs
    setHovered(null)
    setWaitingTopic((w) => (w === name ? w : null)) // un autre topic repart en rejeu
  }, [])
  // « Voir » d'une alerte : son topic, son capteur isole (mises a jour
  // groupees : le setSensor final l'emporte sur celui de selectTopic)
  const showAlert = useCallback((alert: Alert) => {
    selectTopic(alert.topic)
    setSensor(alert.node_id)
  }, [selectTopic])
  const toggleSensor = useCallback((id: string) => setSensor((s) => (s === id ? 'all' : id)), [])
  const showAllSensors = useCallback(() => setSensor('all'), [])
  // Changer de vue demonte la legende (ou le tableau) : la ligne survolee ne
  // recoit jamais son mouseleave, le survol est donc remis a zero ici.
  const changeView = useCallback((v: ViewMode) => {
    setView(v)
    setHovered(null)
  }, [])
  const toggleView = useCallback(() => {
    // le contenu focalise est demonte : le focus passe au bouton de vue coche
    updateKeepingFocus(() => {
      setView((v) => (v === 'chart' ? 'table' : 'chart'))
      setHovered(null)
    }, checkedOr(CHECKED_VIEW))
  }, [])
  // « Afficher tout » de l'etat « aucune mesure dans la plage » : cet etat et
  // son bouton sont remplaces par le graphe ou le tableau
  const showAllRange = useCallback(() => {
    updateKeepingFocus(() => setRange('all'), checkedOr(CHECKED_RANGE))
  }, [])
  const selectRangeIndex = useCallback((i: number) => {
    const preset = RANGE_PRESETS[i]
    if (!preset) return
    // une plage plus courte peut demonter le bouton « lignes de plus » du tableau
    updateKeepingFocus(() => setRange(preset.value), checkedOr(CHECKED_RANGE))
  }, [])

  useKeyboardShortcuts({ onRange: selectRangeIndex, onToggleView: toggleView, onEscape: showAllSensors })

  // En-tete de la carte
  const shownCount = shownIds.length
  const sensorsLabel = `${shownCount} capteur${shownCount > 1 ? 's' : ''}`
  let minFirstT = Infinity
  for (const id of shownIds) {
    const stats = byId[id]?.stats
    if (stats && stats.firstT < minFirstT) minFirstT = stats.firstT
  }
  const title = topic ? (unit ? `${topicLabel(topic)} · ${unit}` : topicLabel(topic)) : 'Mesures'
  const span = Number.isFinite(minFirstT) ? ` (${fmtDuration(anchorT - minFirstT)})` : ''
  const windowLabel = range === 'all'
    ? `Tout l’historique${span}`
    : range === ONE_HOUR ? 'Dernière heure' : `Dernières ${rangeLabel(range)}`
  const subtitle = emptyState
    ? EMPTY_LABEL[emptyState]
    : `${windowLabel} · ${sensorsLabel} · ${fmtCount(totalPoints)} points`
  // Historique affiche > 24 h : l'heure seule serait ambigue (axe, infobulle, tableau)
  const longSpan = rows.length > 1 && rows[rows.length - 1].t - rows[0].t > ONE_DAY
  const heroStats = sensor !== 'all' ? byId[sensor]?.stats : undefined
  const hero = heroStats
    ? { value: fmtValue(heroStats.last, meta.decimals), unit, caption: names[sensor] ?? sensor }
    : undefined
  const tileRangeLabel = range === 'all' ? 'l’historique' : rangeLabel(range)

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
          <EmptyState kind="empty-range" onShowAll={showAllRange} />
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
        {/* Landmark main : onglets, filtres, tiles et carte (l'app bar est le
            seul banner). Cible du lien d'evitement : focalisable par script
            seulement ; id="main" reste sur le tabpanel (aria-controls). */}
        <main id={MAIN_ID} className="shell__main" tabIndex={-1}>
          {topicsError ? (
            <EmptyState kind="api-error" onRetry={loadTopics} />
          ) : noTopics ? (
            <EmptyState kind="no-topics" onRetry={loadTopics} />
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
                unit={unit} decimals={meta.decimals} polarity={meta.polarity} rangeLabel={tileRangeLabel}
                selected={sensor} hovered={hoveredId} alerts={sensorAlerts} emptyKind={emptyState}
                onToggle={toggleSensor} onHover={setHovered}
              />
              <ChartCard
                id="main"
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
