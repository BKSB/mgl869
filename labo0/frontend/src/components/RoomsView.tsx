import { fmtTime } from '../format'
import { roomHash } from '../route'
import type { RoomsData } from '../types'
import { SensorTile } from './SensorTile'
import { EmptyState, Segmented, StatusBadge, Thresholds } from './StatusBadge'

interface Props {
  data: RoomsData | null
  range: string
  onRange: (id: string) => void
  now: number
}

export function RoomsView({ data, range, onRange, now }: Props) {
  if (!data) return <EmptyState text="Chargement…" />
  const { rooms, room } = data
  return (
    <div className="rooms-layout">
      <aside className="sidebar" aria-label="Pièces">
        <div className="sidebar-title">Pièces · {rooms.length}</div>
        <ul className="room-list">
          {rooms.map((r) => (
            <li key={r.id}>
              <a
                className={`room-item${room?.id === r.id ? ' is-active' : ''}`}
                href={roomHash(r.id)}
                aria-current={room?.id === r.id ? 'page' : undefined}
              >
                <span className={`dot dot--${r.status}`} />
                <span className="room-name">{r.name}</span>
                {r.floor && <span className="room-floor">{r.floor}</span>}
              </a>
            </li>
          ))}
        </ul>
      </aside>
      <section className="content">
        {room ? (
          <>
            <div className="page-head">
              <div>
                <div className="eyebrow">{[room.floor, room.building].filter(Boolean).join(' · ')}</div>
                <h1 className="page-title">{room.name}</h1>
                <div className="page-meta">
                  <StatusBadge status={room.status} label={room.status_label} />
                  <span>{room.summary}</span>
                  <span>Dernier message : {fmtTime(room.last_ms)}</span>
                </div>
              </div>
              <Segmented options={data.ranges} value={range} onChange={onRange} label="Plage" />
            </div>
            <div className="tile-grid tile-grid--3">
              {room.sensors.map((tile) => (
                <SensorTile
                  key={`${tile.metric}:${tile.id}`}
                  tile={tile}
                  title={tile.label}
                  subtitle={<code>{tile.id}</code>}
                  footer={
                    tile.thresholds.length > 0 ? (
                      <>
                        Seuils : <Thresholds items={tile.thresholds} short />
                      </>
                    ) : (
                      'Aucun seuil'
                    )
                  }
                  now={now}
                />
              ))}
            </div>
            <p className="footnote">Valeurs, seuils et états fournis par le backend · le frontend affiche seulement.</p>
          </>
        ) : (
          <EmptyState text={rooms.length > 0 ? 'Pièce introuvable.' : 'En attente des premières mesures…'} />
        )}
      </section>
    </div>
  )
}
