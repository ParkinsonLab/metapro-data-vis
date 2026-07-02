import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createSidecarProxyHandler } from '../server/fastapi_sidecar_proxy'

// Generic proxy behaviour is tested once (chord as stand-in). New sidecar routes
// do not need per-channel duplicate suites unless route-specific wiring differs.

describe('createSidecarProxyHandler', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('uses legacy handler when backend query param absent', async () => {
    const legacy = vi.fn().mockReturnValue({ count_matrix: [] })
    const handler = createSidecarProxyHandler({
      legacyHandler: legacy,
      apiPath: '/api/viz/chord',
      label: 'chord',
    })
    const req = { query: {}, body: { names: ['x.tsv'] } }
    const out = await handler(req)
    expect(legacy).toHaveBeenCalledWith(req.body)
    expect(out).toEqual({ ok: true, value: { count_matrix: [] } })
  })

  it('proxies to FastAPI when backend=duckdb', async () => {
    const legacy = vi.fn()
    const envelope = { ok: true, value: { count_matrix: [[1]] } }
    const fetchFn = vi.fn().mockResolvedValue({
      json: () => Promise.resolve(envelope),
    })
    const handler = createSidecarProxyHandler({
      legacyHandler: legacy,
      apiPath: '/api/viz/chord',
      label: 'chord',
      fetchFn,
      baseUrl: 'http://test:8001',
    })
    const req = { query: { backend: 'duckdb' }, body: { names: ['x.tsv'] } }
    const out = await handler(req)
    expect(legacy).not.toHaveBeenCalled()
    expect(fetchFn).toHaveBeenCalledWith('http://test:8001/api/viz/chord', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req.body),
    })
    expect(out).toEqual(envelope)
  })

  it('returns error envelope when fetch fails', async () => {
    const fetchFn = vi.fn().mockRejectedValue(new Error('connection refused'))
    const handler = createSidecarProxyHandler({
      legacyHandler: vi.fn(),
      apiPath: '/api/viz/chord',
      label: 'chord',
      fetchFn,
    })
    const req = { query: { backend: 'duckdb' }, body: {} }
    const out = await handler(req)
    expect(out).toEqual({
      ok: false,
      error: 'chord duckdb backend unavailable: connection refused',
    })
  })
})
