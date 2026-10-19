import { useCallback, useEffect, useState } from 'react'
import type { ThemeMode } from '../types'
import { useMediaQuery } from './useMediaQuery'

const STORAGE_KEY = 'gridd.theme'
const DARK_QUERY = '(prefers-color-scheme: dark)'
const THEME_COLOR = { light: '#f9f9f7', dark: '#0d0d0d' } as const

function readStoredMode(): ThemeMode {
  try {
    const t = localStorage.getItem(STORAGE_KEY)
    if (t === 'light' || t === 'dark') return t
  } catch {
    // stockage indisponible (navigation privee, politique) : mode systeme
  }
  return 'system'
}

/**
 * Bascule Systeme / Clair / Sombre : pose data-theme sur <html>, persiste le
 * choix et tient a jour meta[name=theme-color]. Le script inline d'index.html
 * applique le meme attribut avant le premier rendu (aucun flash).
 */
export function useTheme(): {
  mode: ThemeMode
  resolved: 'light' | 'dark'
  setMode: (m: ThemeMode) => void
} {
  const [mode, setModeState] = useState<ThemeMode>(readStoredMode)
  const systemDark = useMediaQuery(DARK_QUERY)
  const resolved: 'light' | 'dark' = mode === 'system' ? (systemDark ? 'dark' : 'light') : mode

  useEffect(() => {
    const el = document.documentElement
    if (mode === 'system') delete el.dataset.theme
    else el.dataset.theme = mode
    try {
      if (mode === 'system') localStorage.removeItem(STORAGE_KEY)
      else localStorage.setItem(STORAGE_KEY, mode)
    } catch {
      // stockage indisponible : le choix vaut pour la session
    }
  }, [mode])

  useEffect(() => {
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLOR[resolved])
  }, [resolved])

  const setMode = useCallback((m: ThemeMode) => setModeState(m), [])
  return { mode, resolved, setMode }
}
