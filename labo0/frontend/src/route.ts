/** Navigation par hash : #/rooms/<id>, #/metrics/<id>, #/alerts,
 * #/chart/<metrique>/<capteur>. */

export type Route =
  | { view: 'rooms'; room?: string }
  | { view: 'metric'; metric?: string }
  | { view: 'alerts' }
  | { view: 'chart'; metric: string; sensor: string }

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
  const [view = '', first = '', second = ''] = hash.replace(/^#\/?/, '').split('/')
  const id = decode(first)
  if (view === 'metrics') return id ? { view: 'metric', metric: id } : { view: 'metric' }
  if (view === 'alerts') return { view: 'alerts' }
  if (view === 'chart') {
    const sensor = decode(second)
    if (id && sensor) return { view: 'chart', metric: id, sensor }
    return { view: 'rooms' }
  }
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
    case 'chart':
      return `#/chart/${encodeURIComponent(route.metric)}/${encodeURIComponent(route.sensor)}`
  }
}

export const roomHash = (id: string): string => toHash({ view: 'rooms', room: id })

export const chartHash = (metric: string, sensor: string): string => toHash({ view: 'chart', metric, sensor })
