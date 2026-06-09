export type ApiEnvelope<T = unknown> =
  | { ok: true; value: T }
  | { ok: false; error: string }

export const wrapHandler = <T>(fn: (params?: unknown) => T) => {
  return (params?: unknown): ApiEnvelope<T> => {
    try {
      const value = fn(params)
      return { ok: true, value }
    } catch (err) {
      const error = err instanceof Error ? err.message : String(err)
      console.error('[api] handler threw:', err)
      return { ok: false, error }
    }
  }
}
