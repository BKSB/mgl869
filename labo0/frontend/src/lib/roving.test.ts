import { describe, expect, it } from 'vitest'
import { rovingIndex } from './roving'

describe('rovingIndex', () => {
  it('wrapping arrows, Home and End', () => {
    expect(rovingIndex('ArrowRight', 2, 3)).toBe(0)
    expect(rovingIndex('ArrowLeft', 0, 3)).toBe(2)
    expect(rovingIndex('ArrowDown', 0, 3)).toBe(1)
    expect(rovingIndex('ArrowUp', 1, 3)).toBe(0)
    expect(rovingIndex('Home', 2, 3)).toBe(0)
    expect(rovingIndex('End', 0, 3)).toBe(2)
  })

  it('horizontal tabs: up and down ignored', () => {
    expect(rovingIndex('ArrowDown', 0, 3, { vertical: false })).toBeNull()
    expect(rovingIndex('ArrowUp', 1, 3, { vertical: false })).toBeNull()
    expect(rovingIndex('ArrowRight', 0, 3, { vertical: false })).toBe(1)
  })

  it('other key: null', () => {
    expect(rovingIndex('Enter', 0, 3)).toBeNull()
    expect(rovingIndex('a', 0, 3)).toBeNull()
  })
})
