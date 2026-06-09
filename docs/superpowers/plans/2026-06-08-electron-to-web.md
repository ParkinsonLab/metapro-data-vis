# Electron → Web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Electron IPC with a local Docker-hosted Express API + browser frontend, reusing existing data/viz logic unchanged.

**Architecture:** Strangler migration — stand up `src/server/` (Express) wrapping moved `data_functions` handlers, swap renderer `ipc.ts` → `api.ts` (`fetch`), add Vite-only frontend build with dev proxy, package as monolith Docker image, then delete Electron.

**Tech Stack:** Node 22, Express, multer, Vite 7, React 19, Zustand, Vitest, Supertest, Docker

**Spec:** `docs/superpowers/specs/2026-06-08-electron-to-web-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/server/index.ts` | Create | Express entry: CORS, routes, static `dist/`, listen |
| `src/server/envelope.ts` | Create | `wrapHandler()` → `{ ok, value/error }` |
| `src/server/data_functions.ts` | Move from `src/main/` | Parsing, aggregation, in-memory state |
| `src/server/db_functions.ts` | Move from `src/main/` | SQLite via `TAXONOMY_DB_PATH` env |
| `src/server/parse.ts` | Move from `src/main/` | Chord/krona matrix helpers |
| `src/server/utils.ts` | Move from `src/main/` | Shared constants/helpers |
| `src/renderer/src/api.ts` | Create (replaces `ipc.ts`) | `fetch`-based `request()` + endpoint map |
| `vite.config.ts` | Create | React build, dev proxy `/api` → `:3001` |
| `tsconfig.server.json` | Create | Compile `src/server/**` → `out/server/` |
| `tsconfig.web.json` | Modify | Drop Electron/preload references |
| `tsconfig.json` | Modify | Reference `tsconfig.server.json` not `tsconfig.node.json` |
| `src/tests/server.test.ts` | Create | Supertest smoke tests for API routes |
| `src/tests/*.test.ts` | Modify | Import paths `../main/` → `../server/` |
| `Dockerfile` | Create | Multi-stage build + runtime |
| `.dockerignore` | Create | Exclude dev artifacts |
| `package.json` | Modify | Scripts, deps (express, multer, cors, concurrently, tsx; remove electron) |
| `src/renderer/src/App.tsx` | Modify | Remove IPC listeners; handshake via `request()` |
| `src/renderer/src/components/Upload.tsx` | Modify | `FormData` multipart upload |
| `src/renderer/index.html` | Modify | Title, relax CSP for dev proxy |
| `README.md`, `SPEC.md` | Modify | Docker usage, architecture |
| `src/main/**`, `src/preload/**` | Delete | Electron shell |
| `electron.vite.config.ts`, `electron-builder.yml`, `dev-app-update.yml` | Delete | Electron tooling |
| `src/renderer/src/ipc.ts` | Delete | Replaced by `api.ts` |

---

## Task 1: Move backend logic to `src/server/`

**Files:**
- Create: `src/server/data_functions.ts`, `src/server/db_functions.ts`, `src/server/parse.ts`, `src/server/utils.ts`
- Delete: `src/main/data_functions.ts`, `src/main/db_functions.ts`, `src/main/parse.ts`, `src/main/utils.ts`
- Modify: `src/tests/data_functions.test.ts`, `src/tests/db_functions.test.ts`, `src/tests/api.test.ts`

- [ ] **Step 1: Copy backend modules**

```bash
mkdir -p src/server
cp src/main/data_functions.ts src/main/db_functions.ts src/main/parse.ts src/main/utils.ts src/server/
```

- [ ] **Step 2: Add env-based DB path in `src/server/db_functions.ts`**

Replace the hardcoded path in `check_db`:

```ts
const DB_PATH = process.env.TAXONOMY_DB_PATH ?? 'resources/db/taxonomy.db'

const check_db = (): boolean => {
  try {
    db = new DatabaseSync(DB_PATH)
    return true
  } catch (error) {
    return false
  }
}
```

- [ ] **Step 3: Update test imports**

In all three test files, change:

```ts
from '../main/data_functions'  // → '../server/data_functions'
from '../main/db_functions'    // → '../server/db_functions'
```

- [ ] **Step 4: Run tests**

```bash
npm test
```

Expected: PASS (same as before; logic unchanged)

- [ ] **Step 5: Commit**

```bash
git add src/server/ src/tests/ && git rm src/main/data_functions.ts src/main/db_functions.ts src/main/parse.ts src/main/utils.ts
git commit -m "refactor: move backend logic from src/main to src/server"
```

---

## Task 2: Envelope helper + Express skeleton

**Files:**
- Create: `src/server/envelope.ts`, `src/server/index.ts`
- Create: `src/tests/server.test.ts`
- Modify: `package.json` (add express, cors, multer, supertest, @types/express, @types/multer, @types/supertest, concurrently, tsx)

- [ ] **Step 1: Install server dependencies**

```bash
npm install express cors multer
npm install -D @types/express @types/multer supertest @types/supertest concurrently tsx
```

- [ ] **Step 2: Write `src/server/envelope.ts`**

```ts
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
```

- [ ] **Step 3: Write failing health test**

Create `src/tests/server.test.ts`:

```ts
import { describe, it, expect, beforeAll } from 'vitest'
import request from 'supertest'
import { createApp } from '../server/index'

describe('API /api/health', () => {
  const app = createApp()

  it('returns envelope with status 0 or 3 depending on DB', async () => {
    const res = await request(app).get('/api/health')
    expect(res.status).toBe(200)
    expect(res.body).toHaveProperty('ok', true)
    expect([0, 3]).toContain(res.body.value)
  })
})
```

- [ ] **Step 4: Export `createApp` from `src/server/index.ts` (minimal)**

```ts
import express, { type Express } from 'express'
import cors from 'cors'
import { initialize } from './data_functions'
import { wrapHandler } from './envelope'

export const createApp = (): Express => {
  const app = express()
  app.use(cors({ origin: ['http://localhost:5173'], credentials: true }))
  app.use(express.json())

  app.get('/api/health', (_req, res) => {
    const envelope = wrapHandler(initialize)()
    res.status(200).json(envelope)
  })

  return app
}

const port = Number(process.env.PORT ?? 3001)
if (require.main === module) {
  createApp().listen(port, () => console.log(`API listening on :${port}`))
}
```

- [ ] **Step 5: Run test**

```bash
npm test -- src/tests/server.test.ts
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/server/envelope.ts src/server/index.ts src/tests/server.test.ts package.json package-lock.json
git commit -m "feat: add Express server skeleton with /api/health"
```

---

## Task 3: Register all viz + data routes

**Files:**
- Modify: `src/server/index.ts`
- Modify: `src/tests/server.test.ts`

- [ ] **Step 1: Add viz route test**

Append to `src/tests/server.test.ts`:

```ts
describe('API /api/viz/overview', () => {
  const app = createApp()

  it('returns envelope (may error if no data loaded)', async () => {
    const res = await request(app)
      .post('/api/viz/overview')
      .send({ names: ['nonexistent.tsv'] })
    expect(res.status).toBe(200)
    expect(res.body).toHaveProperty('ok')
  })
})
```

- [ ] **Step 2: Register all routes in `src/server/index.ts`**

Mirror the handler registry from `src/main/index.ts`:

```ts
import {
  parse_ec_chord,
  add_data,
  parse_krona,
  parse_network,
  parse_pathway_list,
  parse_counts,
  parse_overview,
  add_test_data
} from './data_functions'

const vizRoutes: Array<{ path: string; handler: (params?: unknown) => unknown }> = [
  { path: '/api/viz/overview', handler: parse_overview },
  { path: '/api/viz/counts', handler: parse_counts },
  { path: '/api/viz/krona', handler: parse_krona },
  { path: '/api/viz/chord', handler: parse_ec_chord },
  { path: '/api/viz/network', handler: parse_network },
  { path: '/api/viz/pathway-list', handler: parse_pathway_list }
]

// Inside createApp(), after health route:
for (const { path, handler } of vizRoutes) {
  app.post(path, (req, res) => {
    const envelope = wrapHandler(handler)(req.body)
    res.status(200).json(envelope)
  })
}

// Dev-only test data loader
app.post('/api/data/test', (req, res) => {
  if (process.env.NODE_ENV === 'production') {
    res.status(404).json({ ok: false, error: 'Not found' })
    return
  }
  const envelope = wrapHandler(add_test_data)()
  res.status(200).json(envelope)
})
```

- [ ] **Step 3: Run tests**

```bash
npm test -- src/tests/server.test.ts
npm test
```

Expected: PASS

- [ ] **Step 4: Manual smoke test**

```bash
npx tsx src/server/index.ts &
curl -s http://localhost:3001/api/health | jq .
kill %1
```

Expected: `{ "ok": true, "value": 0 }` (if `resources/db/taxonomy.db` exists) or `value: 3`

- [ ] **Step 5: Commit**

```bash
git add src/server/index.ts src/tests/server.test.ts
git commit -m "feat: add viz and load_test API routes"
```

---

## Task 4: File upload route (multipart)

**Files:**
- Modify: `src/server/index.ts`
- Modify: `src/tests/server.test.ts`

- [ ] **Step 1: Write upload test**

```ts
import path from 'path'
import fs from 'fs'

describe('API POST /api/data', () => {
  const app = createApp()
  const fixture = path.join(__dirname, '../../resources/example_data/test_rpkm_1.tsv')

  it('loads a TSV via multipart upload', async () => {
    if (!fs.existsSync(fixture)) {
      console.warn('fixture missing, skipping')
      return
    }
    const res = await request(app)
      .post('/api/data')
      .field('name', 'test-upload.tsv')
      .attach('file', fixture)
    expect(res.status).toBe(200)
    expect(res.body).toEqual({ ok: true, value: 'test-upload.tsv' })
  })
})
```

- [ ] **Step 2: Add multer upload route**

```ts
import multer from 'multer'

const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 200 * 1024 * 1024 } })

// Inside createApp():
app.post('/api/data', upload.single('file'), (req, res) => {
  const name = req.body.name as string
  if (!name || !req.file) {
    res.status(200).json({ ok: false, error: 'name and file are required' })
    return
  }
  const data = req.file.buffer.toString('utf8')
  const envelope = wrapHandler(add_data)({ name, data })
  res.status(200).json(envelope)
})
```

- [ ] **Step 3: Run tests**

```bash
npm test -- src/tests/server.test.ts
```

Expected: PASS (upload test passes if fixture exists; skips otherwise)

- [ ] **Step 4: Commit**

```bash
git add src/server/index.ts src/tests/server.test.ts
git commit -m "feat: add multipart file upload at POST /api/data"
```

---

## Task 5: Static file serving + production `start`

**Files:**
- Modify: `src/server/index.ts`
- Create: `tsconfig.server.json`
- Modify: `package.json` (add `dev:api`, `build:api`, `start` scripts)

- [ ] **Step 1: Create `tsconfig.server.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "CommonJS",
    "moduleResolution": "node",
    "outDir": "out/server",
    "rootDir": "src/server",
    "strict": false,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "resolveJsonModule": true,
    "types": ["node"]
  },
  "include": ["src/server/**/*"]
}
```

- [ ] **Step 2: Add static serving to `createApp()`**

```ts
import path from 'path'

// After API routes, before return app:
const distPath = path.join(__dirname, '../../dist')
app.use(express.static(distPath))
app.get(/^(?!\/api).*/, (_req, res) => {
  res.sendFile(path.join(distPath, 'index.html'))
})
```

Note: when compiled, `__dirname` is `out/server/`, so `../../dist` resolves to project `dist/`.

- [ ] **Step 3: Add scripts to `package.json`**

```json
"dev:api": "tsx watch src/server/index.ts",
"build:api": "tsc -p tsconfig.server.json",
"start": "node out/server/index.js"
```

Default `PORT` for production: change listen default to `8080` when `NODE_ENV === 'production'`, else `3001`:

```ts
const port = Number(process.env.PORT ?? (process.env.NODE_ENV === 'production' ? 8080 : 3001))
```

- [ ] **Step 4: Build and smoke test**

```bash
npm run build:api
node out/server/index.js &
curl -s http://localhost:3001/api/health
kill %1
```

Expected: health JSON response

- [ ] **Step 5: Commit**

```bash
git add tsconfig.server.json src/server/index.ts package.json
git commit -m "feat: add static dist serving and production start script"
```

---

## Task 6: Frontend API client (`api.ts`)

**Files:**
- Create: `src/renderer/src/api.ts`
- Modify: `src/renderer/src/App.tsx`

- [ ] **Step 1: Create `src/renderer/src/api.ts`**

```ts
import { useAppStore } from './store/AppStore'

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
    overview: { method: 'POST', url: '/api/viz/overview' },
    counts: { method: 'POST', url: '/api/viz/counts' },
    krona: { method: 'POST', url: '/api/viz/krona' },
    chord: { method: 'POST', url: '/api/viz/chord' },
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
      fetchInit = { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(params ?? {}) }
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
```

- [ ] **Step 2: Refactor `App.tsx`**

Replace `ipc` import and `register_handlers`:

```ts
import { type Channel, registerChannelHandler, request } from './api'

// Keep channel_handlers object as-is, but register via:
useEffect(() => {
  for (const [channel, handler] of Object.entries(channel_handlers) as [Channel, (v: unknown) => void][]) {
    registerChannelHandler(channel, handler)
  }
  request('handshake', undefined, { silent: true })
}, [])
```

Remove `register_handlers` function and all `window.electron` references.

- [ ] **Step 3: Update component imports**

In `Upload.tsx`, `Overview.tsx`, `Krona.tsx`, `Network.tsx`:

```ts
import { request } from '../api'  // was '../ipc'
```

- [ ] **Step 4: Commit** (Electron still present; web client not yet runnable without vite proxy — that's Task 7)

```bash
git add src/renderer/src/api.ts src/renderer/src/App.tsx src/renderer/src/components/
git commit -m "feat: replace IPC client with fetch-based api.ts"
```

---

## Task 7: Vite config + dev workflow

**Files:**
- Create: `vite.config.ts`
- Modify: `package.json`, `tsconfig.web.json`, `src/renderer/index.html`
- Delete: (later in Task 9) `ipc.ts`

- [ ] **Step 1: Create `vite.config.ts`**

```ts
import { resolve } from 'path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  root: resolve(__dirname, 'src/renderer'),
  publicDir: resolve(__dirname, 'src/renderer/public'),
  build: {
    outDir: resolve(__dirname, 'dist'),
    emptyOutDir: true
  },
  resolve: {
    alias: {
      '@renderer': resolve(__dirname, 'src/renderer/src')
    }
  },
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:3001',
        changeOrigin: true
      }
    }
  }
})
```

- [ ] **Step 2: Update `package.json` scripts**

```json
"dev:web": "vite",
"dev": "concurrently -n api,web -c blue,green \"npm run dev:api\" \"npm run dev:web\"",
"build:web": "vite build",
"build": "npm run typecheck && npm run build:web && npm run build:api",
"typecheck:server": "tsc --noEmit -p tsconfig.server.json",
"typecheck": "npm run typecheck:server && npm run typecheck:web"
```

Remove `typecheck:node` (or repoint to `typecheck:server`). Remove `postinstall` electron-builder hook.

- [ ] **Step 3: Update `tsconfig.web.json`**

Remove preload references; use standalone config:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": false,
    "composite": true,
    "baseUrl": ".",
    "paths": { "@renderer/*": ["src/renderer/src/*"] },
    "types": ["vite/client"]
  },
  "include": ["src/renderer/src/**/*", "src/renderer/src/**/*.tsx"]
}
```

- [ ] **Step 4: Update `src/renderer/index.html`**

```html
<title>Metapro Viz</title>
<!-- Remove or relax CSP meta tag for dev; production same-origin is fine -->
```

- [ ] **Step 5: Manual dev smoke test**

```bash
npm run dev
# Open http://localhost:5173
# Click "Load Test Files" (dev only) — verify data loads and visualizations render
```

Expected: App loads, handshake succeeds, test files load

- [ ] **Step 6: Commit**

```bash
git add vite.config.ts package.json tsconfig.web.json src/renderer/index.html
git commit -m "feat: add Vite dev server with API proxy"
```

---

## Task 8: Multipart upload in `Upload.tsx`

**Files:**
- Modify: `src/renderer/src/components/Upload.tsx`

- [ ] **Step 1: Replace FileReader upload with FormData**

```ts
const handleUploadClick = (_event: React.MouseEvent<HTMLButtonElement>) => {
  if (data_file && data_name) {
    const form = new FormData()
    form.append('name', data_name)
    form.append('file', data_file)
    request('load', form)
  }
}
```

Remove `FileReader` logic entirely.

- [ ] **Step 2: Manual test**

Upload a real RPKM TSV via the UI; verify it appears in file list dropdown.

- [ ] **Step 3: Commit**

```bash
git add src/renderer/src/components/Upload.tsx
git commit -m "feat: upload TSV via multipart FormData"
```

---

## Task 9: Remove Electron

**Files:**
- Delete: `src/main/index.ts`, `src/preload/`, `electron.vite.config.ts`, `electron-builder.yml`, `dev-app-update.yml`, `src/renderer/src/ipc.ts`, `src/preload/index.d.ts`
- Modify: `package.json`, `tsconfig.json`, `eslint.config.mjs`

- [ ] **Step 1: Remove Electron dependencies**

```bash
npm uninstall electron electron-vite electron-builder electron-updater @electron-toolkit/preload @electron-toolkit/utils @electron-toolkit/eslint-config-prettier @electron-toolkit/eslint-config-ts @electron-toolkit/tsconfig
```

- [ ] **Step 2: Delete Electron files**

```bash
git rm -r src/main src/preload electron.vite.config.ts electron-builder.yml dev-app-update.yml src/renderer/src/ipc.ts
```

- [ ] **Step 3: Update `tsconfig.json`**

```json
{
  "files": [],
  "references": [
    { "path": "./tsconfig.server.json" },
    { "path": "./tsconfig.web.json" }
  ]
}
```

Delete `tsconfig.node.json` if no longer referenced.

- [ ] **Step 4: Clean `package.json`**

Remove `main` field, update `description`, remove `build:mac`/`build:win`/`build:linux`/`build:unpack`/`start` electron scripts. Ensure `start` points to `node out/server/index.js`.

- [ ] **Step 5: Run full verification**

```bash
npm run typecheck
npm test
npm run build
npm start &
# Open http://localhost:8080
kill %1
```

Expected: All pass; production build serves UI + API on :8080

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: remove Electron dependencies and shell"
```

---

## Task 10: Docker image

**Files:**
- Create: `Dockerfile`, `.dockerignore`

- [ ] **Step 1: Create `.dockerignore`**

```
node_modules
out
dist
.git
.github
*.md
resources/scripts
resources/example_data
```

Note: `resources/db/taxonomy.db` must **not** be ignored — it is required in the image.

- [ ] **Step 2: Create `Dockerfile`**

```dockerfile
FROM node:22 AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=8080
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY --from=build /app/out/server ./out/server
COPY --from=build /app/dist ./dist
COPY resources/db/taxonomy.db ./resources/db/taxonomy.db
EXPOSE 8080
CMD ["node", "out/server/index.js"]
```

- [ ] **Step 3: Build and smoke test**

```bash
docker build -t metapro-viz .
docker run --rm -p 8080:8080 metapro-viz
# Open http://localhost:8080
```

Expected: UI loads, health check passes, visualizations work with test upload

- [ ] **Step 4: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "feat: add Docker image for local container deployment"
```

---

## Task 11: Update documentation

**Files:**
- Modify: `README.md`, `SPEC.md`

- [ ] **Step 1: Update `README.md`**

Replace Electron install instructions with:

```markdown
## Usage

docker run -p 8080:8080 metapro-viz
# Open http://localhost:8080

## Development

npm install
npm run dev        # API :3001 + Vite :5173
npm test
npm run build
npm start          # production preview on :8080
```

- [ ] **Step 2: Update `SPEC.md` §2 Architecture**

Replace three-process Electron table with browser + Express server description. Update data flow from IPC to HTTP. Update §8 Build & Run.

- [ ] **Step 3: Commit**

```bash
git add README.md SPEC.md
git commit -m "docs: update README and SPEC for web + Docker architecture"
```

---

## Self-Review (spec coverage)

| Spec requirement | Task |
|---|---|
| Strangler migration | Tasks 1–8 before Task 9 |
| All 9 API endpoints | Tasks 2–4 |
| Envelope HTTP 200 | Task 2 `wrapHandler` |
| Browser upload multipart | Tasks 4, 8 |
| `load_test` gated in production | Task 3 |
| No client timeout | Task 6 (no AbortController) |
| Module-level state OK | Task 1 (no refactor) |
| Node 22 pinned | Already done (pre-plan) |
| `TAXONOMY_DB_PATH` env | Task 1 |
| Vite dev proxy | Task 7 |
| Docker monolith | Task 10 |
| Remove Electron | Task 9 |
| CORS dev only | Task 2 |
| Static + API same port prod | Task 5 |
| README/SPEC update | Task 11 |
| Existing vitest tests pass | Tasks 1, 3, 9 |
| Out of scope items | Not in plan ✓ |

No placeholders. All tasks have concrete file paths and code.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-08-electron-to-web.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
