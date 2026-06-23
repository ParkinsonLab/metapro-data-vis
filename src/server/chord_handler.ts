import { wrapHandler } from './envelope'
import type { ApiEnvelope } from './envelope'

const CHORD_API_URL = process.env.CHORD_API_URL ?? 'http://localhost:8001'

type ChordBody = Record<string, unknown>

export const createChordHandler = (deps: {
  legacyHandler: (params?: unknown) => unknown
  fetchFn?: typeof fetch
}) => {
  const fetchImpl = deps.fetchFn ?? fetch

  return async (req: { query: Record<string, string | undefined>; body: ChordBody }): Promise<ApiEnvelope> => {
    if (req.query.backend !== 'duckdb') {
      return wrapHandler(deps.legacyHandler)(req.body)
    }

    try {
      const url = `${CHORD_API_URL}/api/viz/chord`
      const res = await fetchImpl(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req.body)
      })
      const envelope = (await res.json()) as ApiEnvelope
      return envelope
    } catch (err) {
      const error = err instanceof Error ? err.message : String(err)
      return { ok: false, error: `chord duckdb backend unavailable: ${error}` }
    }
  }
}
