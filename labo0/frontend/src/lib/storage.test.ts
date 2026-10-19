import { afterEach, describe, expect, it, vi } from 'vitest'
import { readStored, writeStored } from './storage'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('local storage', () => {
  it('reads, writes and removes a key', () => {
    const store = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => store.set(k, v),
      removeItem: (k: string) => store.delete(k),
    })
    writeStored('k', 'v')
    expect(readStored('k')).toBe('v')
    writeStored('k', null)
    expect(readStored('k')).toBeNull()
  })

  it('unavailable storage: null read, write without error', () => {
    const refuse = () => {
      throw new DOMException('refuse', 'SecurityError')
    }
    vi.stubGlobal('localStorage', { getItem: refuse, setItem: refuse, removeItem: refuse })
    expect(readStored('k')).toBeNull()
    expect(() => writeStored('k', 'v')).not.toThrow()
    expect(() => writeStored('k', null)).not.toThrow()
  })
})
