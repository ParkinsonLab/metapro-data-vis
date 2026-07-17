import { useAppStore } from './store/AppStore'
import { sidecarQuery } from './vizBackend'

export type ApiEnvelope<T = unknown> =
  | { ok: true; value: T }
  | { ok: false; error: string }

export type Channel =
  | 'handshake'
  | 'load'
  | 'load_test'
  | 'overview'
  | 'counts'
  | 'krona'
  | 'chord'
  | 'network'
  | 'graph'
  | 'pathway_list'

type ChannelHandler = (value: unknown) => void

const channelHandlers: Partial<Record<Channel, ChannelHandler>> = {}

export const registerChannelHandler = (channel: Channel, handler: ChannelHandler): void => {
  channelHandlers[channel] = handler
}

const endpointFor = (channel: Channel): { method: string; url: string } => {
  const map: Record<Channel, { method: string; url: string }> = {
    handshake: { method: 'GET', url: '/api/health' },
    load: { method: 'POST', url: '/api/data' },
    load_test: { method: 'POST', url: '/api/data/test' },
    overview: { method: 'POST', url: `/api/viz/overview${sidecarQuery('overview')}` },
    counts: { method: 'POST', url: '/api/viz/counts' },
    krona: { method: 'POST', url: `/api/viz/krona${sidecarQuery('krona')}` },
    chord: { method: 'POST', url: `/api/viz/chord${sidecarQuery('chord')}` },
    network: { method: 'POST', url: `/api/viz/network${sidecarQuery('network')}` },
    graph: { method: 'POST', url: `/api/viz/graph${sidecarQuery('graph')}` },
    pathway_list: { method: 'POST', url: `/api/viz/pathway-list${sidecarQuery('pathway_list')}` }
  }
  return map[channel]
}

interface RequestOptions {
  silent?: boolean
}

const handleEnvelope = (channel: Channel, payload: ApiEnvelope): void => {
  if (!payload || typeof payload !== 'object' || !('ok' in payload)) {
    console.error(`[api:${channel}] malformed envelope`, payload)
    useAppStore.setState({ last_error: `${channel}: malformed response` })
    return
  }
  if (payload.ok === false) {
    console.error(`[api:${channel}] ${payload.error}`)
    useAppStore.setState({ last_error: `${channel}: ${payload.error}` })
    return
  }
  channelHandlers[channel]?.(payload.value)
}

export interface DatasetEntry {
  sample_id: string
  path: string
  status: string
  last_run_at: string | null
  last_error: string | null
  is_dev_fixture: boolean
  mtime: number
  size: number
}

export interface DatasetsResponse {
  datasets: DatasetEntry[]
  active_sample_id: string | null
}

export interface SelectDatasetResponse {
  status: 'ready' | 'running'
  sample_id?: string
}

export interface DatasetProgress {
  name?: string
  state?: string
  step?: number
  total?: number
  elapsed_s?: number
}

const parseJson = async <T>(res: Response): Promise<T> => {
  const body = await res.json()
  if (!res.ok) {
    const detail =
      typeof body?.detail === 'string'
        ? body.detail
        : typeof body?.error === 'string'
          ? body.error
          : res.statusText
    throw new Error(detail || `HTTP ${res.status}`)
  }
  return body as T
}

export const fetchDatasets = async (): Promise<DatasetsResponse> => {
  const res = await fetch('/api/datasets')
  return parseJson<DatasetsResponse>(res)
}

export const refreshDatasets = async (): Promise<DatasetsResponse> => {
  const res = await fetch('/api/datasets/refresh', { method: 'POST' })
  return parseJson<DatasetsResponse>(res)
}

export const selectDataset = async (sample_id: string): Promise<SelectDatasetResponse> => {
  const res = await fetch('/api/datasets/select', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sample_id })
  })
  return parseJson<SelectDatasetResponse>(res)
}

export interface DatasetEventHandlers {
  onProgress?: (data: DatasetProgress) => void
  onComplete?: (data: { status: string; sample_id: string }) => void
  onError?: (data: { status: string; message: string }) => void
  onConnectionError?: (message: string) => void
}

export const subscribeDatasetEvents = (
  sample_id: string,
  handlers: DatasetEventHandlers
): EventSource => {
  const es = new EventSource(`/api/datasets/${encodeURIComponent(sample_id)}/events`)

  es.addEventListener('progress', (event) => {
    handlers.onProgress?.(JSON.parse(event.data) as DatasetProgress)
  })
  es.addEventListener('complete', (event) => {
    handlers.onComplete?.(JSON.parse(event.data) as { status: string; sample_id: string })
    es.close()
  })
  es.addEventListener('error', (event) => {
    if (event instanceof MessageEvent) {
      handlers.onError?.(JSON.parse(event.data) as { status: string; message: string })
      es.close()
      return
    }
    handlers.onConnectionError?.('Lost connection to dataset pipeline')
    es.close()
  })

  return es
}

export const request = async (
  channel: Channel,
  params?: unknown,
  opts: RequestOptions = {}
): Promise<void> => {
  if (!opts.silent) {
    useAppStore.setState({ isLoading: true })
  }
  try {
    const { method, url } = endpointFor(channel)
    let fetchInit: RequestInit = { method }

    if (channel === 'load' && params instanceof FormData) {
      fetchInit = { method, body: params }
    } else if (method === 'POST') {
      fetchInit = {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params ?? {})
      }
    }

    const res = await fetch(url, fetchInit)
    const envelope = (await res.json()) as ApiEnvelope
    handleEnvelope(channel, envelope)
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    useAppStore.setState({ last_error: `${channel}: ${msg}` })
  } finally {
    useAppStore.setState({ isLoading: false })
  }
}
