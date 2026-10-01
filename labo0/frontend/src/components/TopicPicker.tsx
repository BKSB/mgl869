import { topicLabel } from '../lib/labels'
import type { TopicInfo } from '../types'

interface Props {
  topics: TopicInfo[]
  selected: string | null
  onSelect: (name: string) => void
}

/** Rangee de pills de selection du topic. */
export function TopicPicker({ topics, selected, onSelect }: Props) {
  return (
    <nav className="topic-picker" aria-label="Choix du topic">
      {topics.map(({ name }) => (
        <button
          key={name}
          className={name === selected ? 'active' : ''}
          onClick={() => onSelect(name)}
        >
          {topicLabel(name)}
        </button>
      ))}
    </nav>
  )
}
