import { wrapHandler } from './envelope'
import type { ApiEnvelope } from './envelope'

const ANALYTICS_API_URL = process.env.ANALYTICS_API_URL ?? 'http://localhost:8001'

export const createSidecarProxyHandler = (deps: {
  legacyHandler: (params?: unknown) => unknown
  apiPath: string
  label: string
  fetchFn?: typeof fetch
  baseUrl?: string
}) => {
  const fetchImpl = deps.fetchFn ?? fetch
  const baseUrl = deps.baseUrl ?? ANALYTICS_API_URL

  return async (req: {
    query: Record<string, string | undefined>
    body: Record<string, unknown>
  }): Promise<ApiEnvelope> => {
    if (req.query.backend !== 'duckdb') {
      return wrapHandler(deps.legacyHandler)(req.body)
    }
    try {
      const url = `${baseUrl}${deps.apiPath}`
      const res = await fetchImpl(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req.body),
      })
      return (await res.json()) as ApiEnvelope
    } catch (err) {
      const error = err instanceof Error ? err.message : String(err)
      return { ok: false, error: `${deps.label} duckdb backend unavailable: ${error}` }
    }
  }
}

export const createChordHandler = (deps: {
  legacyHandler: (params?: unknown) => unknown
  fetchFn?: typeof fetch
}) =>
  createSidecarProxyHandler({
    ...deps,
    apiPath: '/api/viz/chord',
    label: 'chord',
  })
