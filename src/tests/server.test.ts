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
