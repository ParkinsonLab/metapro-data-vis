import path from 'path'
import fs from 'fs'
import { describe, it, expect } from 'vitest'
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

describe('API /api/viz/overview', () => {
  const app = createApp()

  it('returns envelope (may error if no data loaded)', async () => {
    const res = await request(app).post('/api/viz/overview').send({ names: ['nonexistent.tsv'] })
    expect(res.status).toBe(200)
    expect(res.body).toHaveProperty('ok')
  })
})
