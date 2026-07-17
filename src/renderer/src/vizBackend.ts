import { getDataMode } from './dataMode'

const STORAGE_KEY = 'vizBackend'
const MIGRATED_CHANNELS = new Set(['chord', 'graph', 'overview', 'krona', 'pathway_list', 'network'])

export type VizBackend = 'legacy' | 'sidecar'

export function getVizBackend(): VizBackend {
  if (getDataMode() === 'mounted') return 'sidecar'
  return localStorage.getItem(STORAGE_KEY) === 'legacy' ? 'legacy' : 'sidecar'
}

export function sidecarQuery(channel: string): string {
  return MIGRATED_CHANNELS.has(channel) && getVizBackend() === 'sidecar'
    ? '?backend=duckdb'
    : ''
}
