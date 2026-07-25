import { useCallback, useEffect, useRef, useState } from 'react'
import {
  type DatasetEntry,
  type DatasetProgress,
  fetchDatasets,
  refreshDatasets,
  selectDataset,
  subscribeDatasetEvents
} from '../api'
import { useAppStore } from '../store/AppStore'

const applySelection = (entry: DatasetEntry): void => {
  useAppStore.setState({
    selected_file_list: [entry.sample_id]
  })
}

const ProgressBar = ({ progress }: { progress: DatasetProgress | null }) => {
  if (!progress) return null

  const detail = [progress.name, progress.state].filter(Boolean).join(' — ')
  const label = detail
    ? `Processing for visualization — ${detail}`
    : 'Processing for visualization…'
  const hasRatio =
    typeof progress.step === 'number' &&
    typeof progress.total === 'number' &&
    progress.total > 0
  const pct = hasRatio ? Math.min(100, Math.round((progress.step! / progress.total!) * 100)) : null

  return (
    <div style={{ margin: '12px 0', maxWidth: 480 }}>
      <div style={{ fontSize: 13, marginBottom: 4 }}>{label}</div>
      <div
        style={{
          height: 8,
          background: '#e0e0e0',
          borderRadius: 4,
          overflow: 'hidden'
        }}
      >
        <div
          style={{
            height: '100%',
            width: pct !== null ? `${pct}%` : '40%',
            background: '#2c6e9b',
            borderRadius: 4,
            transition: 'width 0.2s ease'
          }}
        />
      </div>
      {hasRatio && (
        <div style={{ fontSize: 12, color: '#555', marginTop: 4 }}>
          Step {progress.step} of {progress.total}
        </div>
      )}
    </div>
  )
}

const DataPanel = (): React.JSX.Element => {
  const [datasets, setDatasets] = useState<DatasetEntry[]>([])
  const [activeSampleId, setActiveSampleId] = useState<string | null>(null)
  const [runningSampleId, setRunningSampleId] = useState<string | null>(null)
  const [progress, setProgress] = useState<DatasetProgress | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const eventSourceRef = useRef<EventSource | null>(null)

  const loadCatalog = useCallback(async () => {
    const data = await fetchDatasets()
    setDatasets(data.datasets)
    setActiveSampleId(data.active_sample_id)
    return data
  }, [])

  useEffect(() => {
    let cancelled = false
    loadCatalog()
      .catch((err) => {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : String(err)
          useAppStore.setState({ last_error: `Data: ${msg}` })
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
      eventSourceRef.current?.close()
    }
  }, [loadCatalog])

  const startEventStream = useCallback(
    (entry: DatasetEntry) => {
      eventSourceRef.current?.close()
      setProgress(null)
      eventSourceRef.current = subscribeDatasetEvents(entry.sample_id, {
        onProgress: (data) => setProgress(data),
        onComplete: async () => {
          applySelection(entry)
          setRunningSampleId(null)
          setProgress(null)
          try {
            await loadCatalog()
          } catch (err) {
            const msg = err instanceof Error ? err.message : String(err)
            useAppStore.setState({ last_error: `Data: ${msg}` })
          }
        },
        onError: (data) => {
          useAppStore.setState({ last_error: data.message })
          setRunningSampleId(null)
          setProgress(null)
        },
        onConnectionError: (message) => {
          useAppStore.setState({ last_error: message })
          setRunningSampleId(null)
          setProgress(null)
        }
      })
    },
    [loadCatalog]
  )

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      const data = await refreshDatasets()
      setDatasets(data.datasets)
      setActiveSampleId(data.active_sample_id)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      useAppStore.setState({ last_error: `Data: ${msg}` })
    } finally {
      setRefreshing(false)
    }
  }

  const handleRowClick = async (entry: DatasetEntry) => {
    if (runningSampleId !== null && runningSampleId !== entry.sample_id) return

    setRunningSampleId(entry.sample_id)
    try {
      const result = await selectDataset(entry.sample_id)
      if (result.status === 'Ready') {
        applySelection(entry)
        setActiveSampleId(entry.sample_id)
        setRunningSampleId(null)
        return
      }
      startEventStream(entry)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      useAppStore.setState({ last_error: `Data: ${msg}` })
      setRunningSampleId(null)
    }
  }

  if (loading) {
    return <p>Loading datasets…</p>
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
        <h3 style={{ margin: 0 }}>Datasets</h3>
        <button onClick={handleRefresh} disabled={refreshing || runningSampleId !== null}>
          {refreshing ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
      <p style={{ margin: '0 0 12px', fontSize: 13, color: '#444', maxWidth: 720 }}>
        Each row is an RPKM_table.tsv in your mounted MetaPro output — click one to process it for
        visualization.
      </p>

      {runningSampleId && <ProgressBar progress={progress} />}

      {datasets.length === 0 ? (
        <p>
          No datasets found. Mount your MetaPro output folder and look for RPKM_table.tsv files there
          (files under <code>vis/</code> are ignored).
        </p>
      ) : (
        <table style={{ borderCollapse: 'collapse', width: '100%', maxWidth: 900 }}>
          <thead>
            <tr>
              <th style={thStyle}>Dataset</th>
              <th style={thStyle}>Path</th>
              <th style={thStyle}>Status</th>
              <th style={thStyle}>Last processed</th>
            </tr>
          </thead>
          <tbody>
            {datasets.map((entry) => {
              const isRunning = runningSampleId === entry.sample_id
              const isDisabled = runningSampleId !== null && !isRunning
              const isActive = activeSampleId === entry.sample_id
              return (
                <tr
                  key={entry.sample_id}
                  onClick={() => !isDisabled && handleRowClick(entry)}
                  style={{
                    cursor: isDisabled ? 'not-allowed' : 'pointer',
                    opacity: isDisabled ? 0.45 : 1,
                    background: isActive ? '#e8f4fc' : isRunning ? '#fff8e6' : undefined
                  }}
                  title={entry.last_error ?? undefined}
                >
                  <td style={tdStyle}>
                    {entry.sample_id}
                    {entry.is_dev_fixture ? ' (example)' : ''}
                  </td>
                  <td style={tdStyle}>{entry.path}</td>
                  <td style={tdStyle}>{entry.status}</td>
                  <td style={tdStyle}>{entry.last_run_at ?? '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}

const thStyle: React.CSSProperties = {
  textAlign: 'left',
  borderBottom: '1px solid #ccc',
  padding: '6px 8px',
  fontSize: 13
}

const tdStyle: React.CSSProperties = {
  borderBottom: '1px solid #eee',
  padding: '6px 8px',
  fontSize: 13,
  verticalAlign: 'top'
}

export default DataPanel
