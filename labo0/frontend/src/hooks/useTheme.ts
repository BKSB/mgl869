import { useCallback, useEffect, useState } from 'react'
import { readStored, writeStored } from '../lib/storage'
import type { ThemeMode } from '../types'
import { useMediaQuery } from './useMediaQuery'

const STORAGE_KEY = 'gridd.theme'
const DARK_QUERY = '(prefers-color-scheme: dark)'
const THEME_COLOR = { light: '#f9f9f7', dark: '#0d0d0d' } as const

function readStoredMode(): ThemeMode {
  const t = readStored(STORAGE_KEY)
  return t === 'light' || t === 'dark' ? t : 'system'
}

/** data-theme sur <html> et meta theme-color. Le script inline d'index.html fait
 * de meme avant le premier rendu (meme cle, memes couleurs) : aucun flash. */
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
    writeStored(STORAGE_KEY, mode === 'system' ? null : mode)
  }, [mode])

  useEffect(() => {
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLOR[resolved])
  }, [resolved])

  const setMode = useCallback((m: ThemeMode) => setModeState(m), [])
  return { mode, resolved, setMode }
}
