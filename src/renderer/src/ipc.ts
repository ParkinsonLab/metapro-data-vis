import { useAppStore } from './store/AppStore'

/**
 * Wire-level envelope produced by every `ipcMain.on('request-*')` handler in
 * `src/main/index.ts`. Mirrored on this side because we don't yet have a
 * `src/shared/` boundary for cross-process types.
 */
export type IPCEnvelope<T = unknown> =
  | { ok: true; value: T }
  | { ok: false; error: string }

/**
 * All channels currently exposed by the main process. Keeping this as a union
 * lets `request(...)` and the response handlers in `App.tsx` catch typos at
 * compile time. Add new channels here when extending `src/main/index.ts:api`.
 */
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

interface RequestOptions {
  /**
   * If true, do not flip `isLoading: true` on send. Use for background pings
   * like the startup `handshake` where the user isn't waiting on a result.
   */
  silent?: boolean
}

/**
 * Fire-and-forget IPC send. The matching response is consumed centrally in
 * `App.tsx`'s `register_handlers`, which clears `isLoading` and routes the
 * envelope to a per-channel handler.
 */
export const request = (
  channel: Channel,
  params?: unknown,
  opts: RequestOptions = {}
): void => {
  if (!opts.silent) {
    useAppStore.setState({ isLoading: true })
  }
  window.electron.ipcRenderer.send(`request-${channel}`, params)
}
