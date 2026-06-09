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
