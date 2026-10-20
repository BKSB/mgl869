/** Acces reseau : URL du WebSocket et seule action envoyee au backend. */

export function wsUrl(path: string): string {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${location.host}${path}`
}

/** POST /api/alerts/<id>/acknowledge ; 404/409 : le detail du backend en erreur. */
export async function acknowledgeAlert(id: string, by: string): Promise<void> {
  const res = await fetch(`/api/alerts/${encodeURIComponent(id)}/acknowledge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ by }),
  })
  if (res.ok) return
  let detail = `HTTP ${res.status}`
  try {
    detail = String((await res.json()).detail ?? detail)
  } catch {
    // corps non JSON : code HTTP seul
  }
  throw new Error(detail)
}
