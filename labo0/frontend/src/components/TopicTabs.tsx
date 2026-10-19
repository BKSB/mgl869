import { useRef } from 'react'
import type { KeyboardEvent } from 'react'
import { Icon } from './Icon'
import { SeverityIcon } from './SeverityIcon'
import { highestSeverity } from '../lib/alerts'
import { plural } from '../lib/format'
import { topicLabel, topicShortLabel } from '../lib/metrics'
import { rovingIndex } from '../lib/roving'
import type { Alert, TopicInfo } from '../types'

/** id du tabpanel : la carte du topic (ChartCard, rendue par App). */
export const TOPIC_PANEL_ID = 'main'

interface Props {
  topics: TopicInfo[]
  selected: string | null
  onSelect: (name: string) => void
  consumers?: Record<string, boolean>
  alertsByTopic?: (topic: string) => Alert[]
}

/** Activation automatique : les fleches selectionnent le topic. */
export function TopicTabs({ topics, selected, onSelect, consumers, alertsByTopic }: Props) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  if (topics.length === 0) return null

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const next = rovingIndex(e.key, i, topics.length, { vertical: false })
    if (next === null) return
    e.preventDefault()
    onSelect(topics[next].name)
    refs.current[next]?.focus()
  }

  return (
    <nav className="tabs">
      <div role="tablist" aria-label="Topics" className="tabs__list">
        {topics.map(({ name }, i) => {
          const active = name === selected
          const stopped = consumers?.[name] === false
          const tabAlerts = alertsByTopic?.(name) ?? []
          const severity = highestSeverity(tabAlerts)
          const titles = [
            stopped ? 'Consommateur Kafka arrêté' : '',
            severity ? plural(tabAlerts.length, 'alerte active', 'alertes actives') : '',
          ].filter(Boolean)
          return (
            <button
              key={name}
              ref={(el) => { refs.current[i] = el }}
              type="button"
              role="tab"
              id={`tab-${name}`}
              aria-selected={active}
              aria-controls={TOPIC_PANEL_ID}
              tabIndex={active ? 0 : -1}
              title={titles.length > 0 ? titles.join(' · ') : undefined}
              className="tab"
              onClick={() => onSelect(name)}
              onKeyDown={(e) => onKeyDown(e, i)}
            >
              {/* Nom accessible : le libelle long ; l'abreviation est visuelle seulement */}
              <span className="tabs__long">{topicLabel(name)}</span>
              <span className="tabs__short" aria-hidden="true">{topicShortLabel(name)}</span>
              {stopped && (
                <>
                  <span className="tabs__dot" aria-hidden="true" />
                  <Icon name="alert-triangle" size={12} className="tab__warn" />
                  <span className="sr-only">, consommateur arrêté</span>
                </>
              )}
              {severity && (
                <>
                  <SeverityIcon severity={severity} size={12} className="tab__alert" />
                  <span className="sr-only">, {plural(tabAlerts.length, 'alerte')}</span>
                </>
              )}
            </button>
          )
        })}
      </div>
    </nav>
  )
}
