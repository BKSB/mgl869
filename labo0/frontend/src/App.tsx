import { useEffect, useMemo, useState } from 'react'
import { fetchTopics } from './api/topics'
import { RangePicker, type TimeRange } from './components/RangePicker'
import { SensorLegend } from './components/SensorLegend'
import { SensorPicker } from './components/SensorPicker'
import { StatusBadge } from './components/StatusBadge'
import { TopicChart } from './components/TopicChart'
import { TopicPicker } from './components/TopicPicker'
import { useTopicStream } from './hooks/useTopicStream'
import { colorSlots, sensorNames } from './lib/sensors'
import type { TopicInfo } from './types'
import './App.css'

export default function App() {
  const [topics, setTopics] = useState<TopicInfo[]>([])
  const [topic, setTopic] = useState<string | null>(null)
  const [sensor, setSensor] = useState<string | 'all'>('all')
  const [range, setRange] = useState<TimeRange>('all')
  const { sensors, status } = useTopicStream(topic)

  useEffect(() => {
    fetchTopics()
      .then((topics) => {
        setTopics(topics)
        setTopic((cur) => cur ?? topics[0]?.name ?? null)
      })
      .catch(() => setTopics([]))
  }, [])

  const sensorIds = useMemo(() => Object.keys(sensors).sort(), [sensors])
  const slots = useMemo(() => colorSlots(sensorIds), [sensorIds])
  const names = useMemo(() => sensorNames(sensors, sensorIds), [sensors, sensorIds])

  const selectTopic = (name: string) => {
    setTopic(name)
    setSensor('all')   // nouveau topic = nouveaux capteurs
  }

  const shown = sensor === 'all' ? sensorIds : sensorIds.filter((s) => s === sensor)

  return (
    <main className="dashboard">
      <header className="masthead">
        <h1>Dashboard gridd</h1>
        <StatusBadge status={status} />
      </header>

      <div className="filters-row">
        <TopicPicker topics={topics} selected={topic} onSelect={selectTopic} />
        <RangePicker selected={range} onSelect={setRange} />
      </div>

      {sensorIds.length > 0 && (
        <SensorPicker
          sensorIds={sensorIds} selected={sensor}
          colorSlots={slots} names={names} onSelect={setSensor}
        />
      )}

      <section className="chart-panel">
        {sensorIds.length > 0 ? (
          <>
            <TopicChart
              sensors={sensors} selected={sensor}
              colorSlots={slots} names={names} range={range}
            />
            <SensorLegend
              sensorIds={shown} sensors={sensors}
              colorSlots={slots} names={names}
            />
          </>
        ) : (
          <p className="empty">
            {status === 'live'
              ? 'En attente de données sur ce topic…'
              : 'Connexion au flux…'}
          </p>
        )}
      </section>
    </main>
  )
}
