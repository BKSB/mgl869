import { useRef } from 'react'
import type { KeyboardEvent } from 'react'
import { Icon } from './Icon'
import { SeverityIcon } from './SeverityIcon'
import { alertCount, highestSeverity } from '../lib/alerts'
import { topicLabel } from '../lib/labels'
import { topicShortLabel } from '../lib/metrics'
import type { Alert, TopicInfo } from '../types'

interface Props {
  topics: TopicInfo[]
  selected: string | null
  onSelect: (name: string) => void
  consumers?: Record<string, boolean>
  /** Alertes actives d'un topic (indicateur sur l'onglet). */
  alertsByTopic?: (topic: string) => Alert[]
}

/** Onglets de topic (role tablist, activation automatique aux fleches).
 * Libelle court sous 720 px ; point + icone si le consommateur est arrete ;
 * icone de severite (12 px) + « n alertes » en sr-only si le topic a des
 * alertes actives. */
export function TopicTabs({ topics, selected, onSelect, consumers, alertsByTopic }: Props) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  if (topics.length === 0) return null

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const n = topics.length
    let next: number
    switch (e.key) {
      case 'ArrowLeft': next = (i - 1 + n) % n; break
      case 'ArrowRight': next = (i + 1) % n; break
      case 'Home': next = 0; break
      case 'End': next = n - 1; break
      default: return
    }
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
            severity ? `${alertCount(tabAlerts.length)} active${tabAlerts.length > 1 ? 's' : ''}` : '',
          ].filter(Boolean)
          return (
            <button
              key={name}
              ref={(el) => { refs.current[i] = el }}
              type="button"
              role="tab"
              id={`tab-${name}`}
              aria-selected={active}
              aria-controls="main"
              tabIndex={active ? 0 : -1}
              title={titles.length > 0 ? titles.join(' · ') : undefined}
              className="tab"
              onClick={() => onSelect(name)}
              onKeyDown={(e) => onKeyDown(e, i)}
            >
              {/* Nom accessible : toujours le libelle long ; l'abreviation
                  (< 720 px) n'est que visuelle */}
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
                  <span className="sr-only">, {alertCount(tabAlerts.length)}</span>
                </>
              )}
            </button>
          )
        })}
      </div>
    </nav>
  )
}
