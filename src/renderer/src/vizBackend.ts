const STORAGE_KEY = 'vizBackend'
const MIGRATED_CHANNELS = new Set(['chord', 'overview', 'krona'])

export type VizBackend = 'legacy' | 'sidecar'

export function getVizBackend(): VizBackend {
  return localStorage.getItem(STORAGE_KEY) === 'legacy' ? 'legacy' : 'sidecar'
}

export function sidecarQuery(channel: string): string {
  return MIGRATED_CHANNELS.has(channel) && getVizBackend() === 'sidecar'
    ? '?backend=duckdb'
    : ''
}
