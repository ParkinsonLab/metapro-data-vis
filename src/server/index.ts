import express, { type Express } from 'express'
import cors from 'cors'
import {
  parse_ec_chord,
  parse_krona,
  parse_network,
  parse_pathway_list,
  parse_counts,
  parse_overview,
  add_test_data,
  initialize
} from './data_functions'
import { wrapHandler } from './envelope'

const vizRoutes: Array<{ path: string; handler: (params?: unknown) => unknown }> = [
  { path: '/api/viz/overview', handler: parse_overview },
  { path: '/api/viz/counts', handler: parse_counts },
  { path: '/api/viz/krona', handler: parse_krona },
  { path: '/api/viz/chord', handler: parse_ec_chord },
  { path: '/api/viz/network', handler: parse_network },
  { path: '/api/viz/pathway-list', handler: parse_pathway_list }
]

export const createApp = (): Express => {
  const app = express()
  app.use(cors({ origin: ['http://localhost:5173'], credentials: true }))
  app.use(express.json())

  app.get('/api/health', (_req, res) => {
    const envelope = wrapHandler(initialize)()
    res.status(200).json(envelope)
  })

  for (const { path, handler } of vizRoutes) {
    app.post(path, (req, res) => {
      const envelope = wrapHandler(handler)(req.body)
      res.status(200).json(envelope)
    })
  }

  app.post('/api/data/test', (req, res) => {
    if (process.env.NODE_ENV === 'production') {
      res.status(404).json({ ok: false, error: 'Not found' })
      return
    }
    const envelope = wrapHandler(add_test_data)()
    res.status(200).json(envelope)
  })

  return app
}

const port = Number(process.env.PORT ?? 3001)
if (require.main === module) {
  createApp().listen(port, () => console.log(`API listening on :${port}`))
}
