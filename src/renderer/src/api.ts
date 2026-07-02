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
    network: { method: 'POST', url: '/api/viz/network' },
    pathway_list: { method: 'POST', url: '/api/viz/pathway-list' }
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
