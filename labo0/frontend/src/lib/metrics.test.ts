import { describe, expect, it } from 'vitest'
import { getTopicMeta, topicLabel, topicShortLabel } from './metrics'

describe('topic metadata', () => {
  it('known label, or capitalized last segment (like the backend)', () => {
    expect(topicLabel('gridd.obs.environmental.co2')).toBe('CO₂')
    expect(topicLabel('gridd.obs.wind.wind_speed')).toBe('Wind speed')
    expect(topicLabel('simple')).toBe('Simple')
  })

  it('decimals, polarity and short label, neutral fallback', () => {
    expect(getTopicMeta('gridd.obs.environmental.co2')).toMatchObject({ decimals: 0, polarity: 'lower-better', shortLabel: 'CO₂' })
    expect(getTopicMeta('gridd.obs.wind.wind_speed')).toMatchObject({ decimals: 1, polarity: 'neutral', shortLabel: 'Wind speed' })
    expect(getTopicMeta(null).decimals).toBe(1)
    expect(topicShortLabel('gridd.obs.environmental.temperature')).toBe('Temp.')
  })
})
