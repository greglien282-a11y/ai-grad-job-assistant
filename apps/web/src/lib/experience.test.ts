import { describe, expect, it, vi } from 'vitest'
import fixtures from '../test/api-fixtures.json'
import { createExperienceApi, credentialsSchema, readCredentials, sessionSchema, SESSION_KEY } from './experience'

describe('FastAPI client contracts and temporary credential storage', () => {
  it('accepts every recorded server snapshot and rejects invalid versions or source shapes', () => {
    for (const key of ['empty', 'pending', 'confirmed', 'edited', 'editedConfirmed', 'verified', 'rejected', 'ended'] as const) {
      expect(sessionSchema.safeParse(fixtures[key]).success).toBe(true)
    }
    expect(sessionSchema.safeParse({ ...fixtures.pending, facts: [{ ...fixtures.pending.facts[0], version: '1' }] }).success).toBe(false)
    expect(sessionSchema.safeParse({ ...fixtures.pending, facts: [{ ...fixtures.pending.facts[0], source_kind: 'AI_verified' }] }).success).toBe(false)
  })
  it('ignores corrupted or extra storage data instead of persisting experience content', () => {
    sessionStorage.setItem(SESSION_KEY, '{broken')
    expect(readCredentials()).toBeNull()
    expect(credentialsSchema.safeParse({ sessionId: fixtures.created.session_id, token: fixtures.created.access_token, facts: fixtures.pending.facts }).success).toBe(false)
  })
  it('never reflects server errors or private payloads to users', async () => {
    const api = createExperienceApi(vi.fn(async () => new Response(JSON.stringify({ error: { code: 'database_unavailable', message: 'PRIVATE SQL OR CREDENTIAL' } }), { status: 503 })) as typeof fetch)
    await expect(api.create('Synthetic')).rejects.toThrow('数据库暂时不可用')
    await expect(api.create('Synthetic')).rejects.not.toThrow('PRIVATE')
  })
  it('rejects successful responses that violate the API contract', async () => {
    const api = createExperienceApi(vi.fn(async () => new Response('{}', { status: 200 })) as typeof fetch)
    await expect(api.create('Synthetic')).rejects.toThrow('资料格式异常')
  })
})
