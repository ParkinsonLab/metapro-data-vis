import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createChordHandler } from '../server/chord_handler'

describe('createChordHandler', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('uses legacy handler when backend query param absent', async () => {
    const legacy = vi.fn().mockReturnValue({ count_matrix: [] })
    const handler = createChordHandler({ legacyHandler: legacy })
    const req = { query: {}, body: { names: ['x.tsv'] } } as any
    const out = await handler(req)
    expect(legacy).toHaveBeenCalledWith(req.body)
    expect(out).toEqual({ ok: true, value: { count_matrix: [] } })
  })
})
