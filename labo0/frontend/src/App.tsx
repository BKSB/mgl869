import { useEffect, useState } from 'react'
import { acknowledgeAlert } from './api'
import { AlertsView } from './components/AlertsView'
import { Header } from './components/Header'
import { MetricView } from './components/MetricView'
import { RoomsView } from './components/RoomsView'
import { Toasts } from './components/Toasts'
import { parseHash } from './route'
import type { Route } from './route'
import type { ViewParams } from './types'
import { useDashboard } from './useDashboard'
import { useNow } from './useNow'

const OPERATOR_KEY = 'gridd.operator'

/** Nom affiche sur les alertes acquittees, demande une fois ; null : annule. */
function operatorName(): string | null {
  let name: string | null = null
  try {
    name = localStorage.getItem(OPERATOR_KEY)
  } catch {
    // stockage indisponible : le nom est redemande
  }
  if (name) return name
  const typed = window.prompt('Votre nom (affiché sur les alertes acquittées) :')
  if (typed === null) return null
  name = typed.trim()
  if (name) {
    try {
      localStorage.setItem(OPERATOR_KEY, name)
    } catch {
      // idem
    }
  }
  return name
}

function toParams(route: Route, range: string, sort: string, filter: string): ViewParams {
  switch (route.view) {
    case 'rooms':
      return { view: 'rooms', room: route.room, range }
    case 'metric':
      return { view: 'metric', metric: route.metric, range, sort }
    case 'alerts':
      return { view: 'alerts', filter }
  }
}

export default function App() {
  const [route, setRoute] = useState<Route>(() => parseHash(location.hash))
  // Controles locaux : le backend applique la plage, le tri et le filtre
  const [range, setRange] = useState('1h')
  const [sort, setSort] = useState('severity')
  const [filter, setFilter] = useState('active')

  useEffect(() => {
    const onHashChange = () => setRoute(parseHash(location.hash))
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  const { status, view, toasts, dismiss } = useDashboard(toParams(route, range, sort, filter))
  const now = useNow()

  const acknowledge = async (id: string) => {
    const by = operatorName()
    if (by === null) return
    try {
      await acknowledgeAlert(id, by)
    } catch (err) {
      window.alert(`Acquittement refusé : ${(err as Error).message}`)
    }
  }

  return (
    <>
      <Header route={route} site={view?.site ?? ''} alertsActive={view?.alerts_active ?? 0} status={status} />
      <main className="main">
        {route.view === 'rooms' && (
          <RoomsView data={view?.view === 'rooms' ? view : null} range={range} onRange={setRange} now={now} />
        )}
        {route.view === 'metric' && (
          <MetricView
            data={view?.view === 'metric' ? view : null}
            range={range}
            onRange={setRange}
            onSort={setSort}
            now={now}
          />
        )}
        {route.view === 'alerts' && (
          <AlertsView data={view?.view === 'alerts' ? view : null} onFilter={setFilter} onAck={acknowledge} />
        )}
      </main>
      <Toasts toasts={toasts} now={now} onDismiss={dismiss} onAck={acknowledge} />
    </>
  )
}
