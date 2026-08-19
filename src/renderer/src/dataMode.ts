const STORAGE_KEY = 'dataMode'

export type DataMode = 'mounted' | 'upload'

function defaultMode(): DataMode {
  const env = import.meta.env.VITE_DATA_MODE
  if (env === 'mounted' || env === 'upload') return env
  return 'upload'
}

export function getDataMode(): DataMode {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored === 'mounted' || stored === 'upload') return stored
  return defaultMode()
}

export function setDataMode(mode: DataMode): void {
  localStorage.setItem(STORAGE_KEY, mode)
  if (mode === 'mounted') {
    localStorage.setItem('vizBackend', 'sidecar')
  }
}
