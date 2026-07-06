import { describe, expect, it } from 'vitest'
import { normalizePathwayListResponse } from '../renderer/src/pathwayListResponse'

describe('normalizePathwayListResponse', () => {
  it('parses wrapper with breakdowns', () => {
    const value = {
      pathways: ['A', 'B'],
      breakdowns: { A: { index: ['p1'], counts: [1] } }
    }
    expect(normalizePathwayListResponse(value)).toEqual(value)
  })

  it('parses wrapper without breakdowns', () => {
    expect(normalizePathwayListResponse({ pathways: ['A'] })).toEqual({
      pathways: ['A'],
      breakdowns: {}
    })
  })

  it('accepts bare string[]', () => {
    expect(normalizePathwayListResponse(['A', 'B'])).toEqual({
      pathways: ['A', 'B'],
      breakdowns: {}
    })
  })

  it('returns empty for invalid input', () => {
    expect(normalizePathwayListResponse(null)).toEqual({
      pathways: [],
      breakdowns: {}
    })
  })
})
