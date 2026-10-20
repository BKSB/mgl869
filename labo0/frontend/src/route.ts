/** Navigation par hash : #/rooms/<id>, #/metrics/<id>, #/alerts. */

export type Route =
  | { view: 'rooms'; room?: string }
  | { view: 'metric'; metric?: string }
  | { view: 'alerts' }

function decode(segment: string): string | undefined {
  if (!segment) return undefined
  try {
    return decodeURIComponent(segment)
  } catch {
    return segment
  }
}

/** Hash inconnu ou vide : les pieces. */
export function parseHash(hash: string): Route {
  const [view = '', segment = ''] = hash.replace(/^#\/?/, '').split('/')
  const id = decode(segment)
  if (view === 'metrics') return id ? { view: 'metric', metric: id } : { view: 'metric' }
  if (view === 'alerts') return { view: 'alerts' }
  return id ? { view: 'rooms', room: id } : { view: 'rooms' }
}

export function toHash(route: Route): string {
  switch (route.view) {
    case 'rooms':
      return route.room ? `#/rooms/${encodeURIComponent(route.room)}` : '#/rooms'
    case 'metric':
      return route.metric ? `#/metrics/${encodeURIComponent(route.metric)}` : '#/metrics'
    case 'alerts':
      return '#/alerts'
  }
}

export const roomHash = (id: string): string => toHash({ view: 'rooms', room: id })
